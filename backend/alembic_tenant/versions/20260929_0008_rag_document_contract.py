"""Add document fingerprints and stable RAG processing error codes."""

from __future__ import annotations

import hashlib

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20260929_0008"
down_revision = "20260926_0007"
branch_labels = None
depends_on = None


def _schema() -> str:
    value = context.config.attributes.get("tenant_schema")
    if not value:
        value = context.get_x_argument(as_dictionary=True).get("tenant_schema")
    if not value:
        raise RuntimeError("tenant_schema Alembic attribute is required")
    return validate_schema_name(str(value))


def upgrade() -> None:
    schema = _schema()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names(schema=schema))

    if "documents" in tables:
        columns = {column["name"] for column in inspector.get_columns("documents", schema=schema)}
        if "content_hash" not in columns:
            op.add_column("documents", sa.Column("content_hash", sa.String(length=64), nullable=True), schema=schema)
        if "error_code" not in columns:
            op.add_column("documents", sa.Column("error_code", sa.String(length=80), nullable=True), schema=schema)

        seen: set[tuple[int | None, str]] = set()
        rows = bind.execute(
            sa.text(
                f'SELECT id, business_id, source_bytes, content_hash FROM "{schema}".documents ORDER BY id'
            )
        ).mappings()
        for row in rows:
            digest = row["content_hash"]
            if not digest and row["source_bytes"]:
                digest = hashlib.sha256(bytes(row["source_bytes"])).hexdigest()
            if not digest:
                continue
            key = (row["business_id"], str(digest))
            persisted_digest = str(digest) if key not in seen else None
            seen.add(key)
            if persisted_digest != row["content_hash"]:
                bind.execute(
                    sa.text(
                        f'UPDATE "{schema}".documents SET content_hash=:digest WHERE id=:document_id'
                    ),
                    {"digest": persisted_digest, "document_id": row["id"]},
                )

        indexes = {index["name"] for index in inspector.get_indexes("documents", schema=schema)}
        if "uq_documents_business_content_hash" not in indexes:
            op.create_index(
                "uq_documents_business_content_hash",
                "documents",
                ["business_id", "content_hash"],
                unique=True,
                schema=schema,
            )

    if "rag_runs" in tables:
        columns = {column["name"] for column in inspector.get_columns("rag_runs", schema=schema)}
        if "error_code" not in columns:
            op.add_column("rag_runs", sa.Column("error_code", sa.String(length=80), nullable=True), schema=schema)


def downgrade() -> None:
    schema = _schema()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names(schema=schema))
    if "rag_runs" in tables:
        columns = {column["name"] for column in inspector.get_columns("rag_runs", schema=schema)}
        if "error_code" in columns:
            op.drop_column("rag_runs", "error_code", schema=schema)
    if "documents" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("documents", schema=schema)}
        if "uq_documents_business_content_hash" in indexes:
            op.drop_index("uq_documents_business_content_hash", table_name="documents", schema=schema)
        columns = {column["name"] for column in inspector.get_columns("documents", schema=schema)}
        for name in ("error_code", "content_hash"):
            if name in columns:
                op.drop_column("documents", name, schema=schema)
