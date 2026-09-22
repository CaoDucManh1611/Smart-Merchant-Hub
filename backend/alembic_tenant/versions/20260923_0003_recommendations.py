"""Add tenant-local recommendation serving, feedback, profiles, and signals.

Revision ID: 20260923_0003
Revises: 20260921_0002
"""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20260923_0003"
down_revision = "20260921_0002"
branch_labels = None
depends_on = None


def _schema() -> str:
    value = context.config.attributes.get("tenant_schema")
    if not value:
        value = context.get_x_argument(as_dictionary=True).get("tenant_schema")
    if not value:
        raise RuntimeError("tenant_schema Alembic attribute is required")
    return validate_schema_name(str(value))


def _fk(schema: str, target: str, *, ondelete: str) -> sa.ForeignKey:
    return sa.ForeignKey(f"{schema}.{target}", ondelete=ondelete)


def _index(table: str, column: str, *, schema: str) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column], schema=schema)


def upgrade() -> None:
    schema = _schema()
    existing = set(sa.inspect(op.get_bind()).get_table_names(schema=schema))

    if "recommendation_requests" not in existing:
        op.create_table(
            "recommendation_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("request_id", sa.String(length=64), nullable=False),
            sa.Column("customer_id", sa.Integer(), _fk(schema, "customers.id", ondelete="SET NULL")),
            sa.Column("experiment_id", sa.Integer(), _fk(schema, "experiments.id", ondelete="SET NULL")),
            sa.Column("bandit_decision_id", sa.Integer(), _fk(schema, "bandit_decisions.id", ondelete="SET NULL")),
            sa.Column("strategy", sa.String(length=40), nullable=False),
            sa.Column("model_version", sa.String(length=80), nullable=False),
            sa.Column("context", sa.JSON(), nullable=False),
            sa.Column("served_items", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "request_id", name="uq_recommendation_request_business_request"),
            schema=schema,
        )
        for column in ("business_id", "request_id", "customer_id", "experiment_id", "bandit_decision_id", "created_at"):
            _index("recommendation_requests", column, schema=schema)

    if "recommendation_feedback" not in existing:
        op.create_table(
            "recommendation_feedback",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("recommendation_request_id", sa.Integer(), _fk(schema, "recommendation_requests.id", ondelete="CASCADE"), nullable=False),
            sa.Column("product_id", sa.Integer(), _fk(schema, "products.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("event_type", sa.String(length=30), nullable=False),
            sa.Column("reward", sa.Numeric(8, 4), nullable=False, server_default="0"),
            sa.Column("idempotency_key", sa.String(length=160), nullable=False),
            sa.Column("event_metadata", sa.JSON(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "idempotency_key", name="uq_recommendation_feedback_business_idempotency"),
            schema=schema,
        )
        for column in ("business_id", "recommendation_request_id", "product_id", "event_type", "occurred_at"):
            _index("recommendation_feedback", column, schema=schema)

    if "recommendation_customer_profiles" not in existing:
        op.create_table(
            "recommendation_customer_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), _fk(schema, "customers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("segment_label", sa.String(length=40), nullable=False),
            sa.Column("features", sa.JSON(), nullable=False),
            sa.Column("model_version", sa.String(length=80), nullable=False),
            sa.Column("trained_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "customer_id", name="uq_recommendation_profile_business_customer"),
            schema=schema,
        )
        for column in ("business_id", "customer_id", "segment_label"):
            _index("recommendation_customer_profiles", column, schema=schema)

    if "recommendation_training_runs" not in existing:
        op.create_table(
            "recommendation_training_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("algorithm", sa.String(length=80), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
            sa.Column("metrics", sa.JSON(), nullable=False),
            sa.Column("artifact", sa.JSON(), nullable=False),
            sa.Column("started_at", sa.DateTime()),
            sa.Column("completed_at", sa.DateTime()),
            sa.Column("error_message", sa.String(length=500)),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            schema=schema,
        )
        for column in ("business_id", "status"):
            _index("recommendation_training_runs", column, schema=schema)

    if "customer_product_interactions" not in existing:
        op.create_table(
            "customer_product_interactions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), _fk(schema, "customers.id", ondelete="SET NULL")),
            sa.Column("product_id", sa.Integer(), _fk(schema, "products.id", ondelete="SET NULL")),
            sa.Column("recommendation_request_id", sa.Integer(), _fk(schema, "recommendation_requests.id", ondelete="SET NULL")),
            sa.Column("order_id", sa.Integer(), _fk(schema, "orders.id", ondelete="SET NULL")),
            sa.Column("event_type", sa.String(length=30), nullable=False),
            sa.Column("source", sa.String(length=30), nullable=False),
            sa.Column("query_text", sa.String(length=1000)),
            sa.Column("idempotency_key", sa.String(length=160), nullable=False),
            sa.Column("event_metadata", sa.JSON(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "idempotency_key", name="uq_recommendation_interaction_business_idempotency"),
            schema=schema,
        )
        for column in ("business_id", "customer_id", "product_id", "recommendation_request_id", "order_id", "event_type", "source", "occurred_at"):
            _index("customer_product_interactions", column, schema=schema)


def downgrade() -> None:
    schema = _schema()
    existing = set(sa.inspect(op.get_bind()).get_table_names(schema=schema))
    for table in (
        "customer_product_interactions",
        "recommendation_training_runs",
        "recommendation_customer_profiles",
        "recommendation_feedback",
        "recommendation_requests",
    ):
        if table in existing:
            op.drop_table(table, schema=schema)
