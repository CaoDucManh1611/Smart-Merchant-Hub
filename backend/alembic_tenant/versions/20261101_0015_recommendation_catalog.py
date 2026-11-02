"""Generic recommendation catalog, interaction versions and per-shop quality gate."""
from alembic import context, op
import sqlalchemy as sa
from app.tenancy.schema import validate_schema_name
revision = "20261101_0015"
down_revision = "20261025_0014"
branch_labels = None
depends_on = None

def _schema():
    value = context.config.attributes.get("tenant_schema") or context.get_x_argument(as_dictionary=True).get("tenant_schema")
    if not value: raise RuntimeError("tenant_schema is required")
    return validate_schema_name(str(value))

def _inspector(schema):
    return sa.inspect(op.get_bind())

def _create_index_if_missing(schema, name, table_name, columns):
    indexes = {item["name"] for item in _inspector(schema).get_indexes(table_name, schema=schema)}
    if name not in indexes:
        op.create_index(name, table_name, columns, schema=schema)

def upgrade():
    schema = _schema()
    existing_tables = set(_inspector(schema).get_table_names(schema=schema))
    if "recommendation_catalog_entries" not in existing_tables:
        op.create_table("recommendation_catalog_entries",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("object_type", sa.String(30), nullable=False), sa.Column("external_id", sa.String(120), nullable=False),
            sa.Column("sku_norm", sa.String(120)), sa.Column("name", sa.String(255), nullable=False), sa.Column("description", sa.Text()),
            sa.Column("status", sa.String(30), nullable=False, server_default="active"), sa.Column("availability", sa.String(30), nullable=False, server_default="in_stock"),
            sa.Column("stock_quantity", sa.Numeric(14,3)), sa.Column("price", sa.Numeric(14,2)), sa.Column("currency", sa.String(3)),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"), sa.Column("source", sa.String(60), nullable=False, server_default="catalog_sync"),
            sa.Column("metadata_", sa.JSON()), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id","object_type","external_id",name="uq_rce_business_type_external"), schema=schema)
    _create_index_if_missing(schema, "ix_rce_shop_live", "recommendation_catalog_entries", ["business_id","status","availability"])
    _create_index_if_missing(schema, "ix_rce_shop_type_live", "recommendation_catalog_entries", ["business_id","object_type","status","availability"])
    _create_index_if_missing(schema, "ix_rce_shop_sku", "recommendation_catalog_entries", ["business_id","sku_norm"])

    existing_tables = set(_inspector(schema).get_table_names(schema=schema))
    if "recommendation_catalog_attributes" not in existing_tables:
        op.create_table("recommendation_catalog_attributes",
            sa.Column("id",sa.Integer(),primary_key=True), sa.Column("catalog_entry_id",sa.Integer(),nullable=False),
            sa.Column("key_norm",sa.String(100),nullable=False),sa.Column("value_type",sa.String(16),nullable=False),sa.Column("normalized_value",sa.String(255),nullable=False),
            sa.Column("text_value",sa.Text()),sa.Column("number_value",sa.Numeric(20,6)),sa.Column("boolean_value",sa.Boolean()),sa.Column("date_value",sa.Date()),
            sa.ForeignKeyConstraint(["catalog_entry_id"],[f"{schema}.recommendation_catalog_entries.id"],ondelete="CASCADE"),
            sa.UniqueConstraint("catalog_entry_id","key_norm","normalized_value",name="uq_rca_entry_key_value"),schema=schema)
    _create_index_if_missing(schema, "ix_rca_exact_lookup", "recommendation_catalog_attributes", ["key_norm","normalized_value"])

    existing_tables = set(_inspector(schema).get_table_names(schema=schema))
    if "recommendation_catalog_chunk_mappings" not in existing_tables:
        op.create_table("recommendation_catalog_chunk_mappings",
            sa.Column("id",sa.Integer(),primary_key=True),sa.Column("catalog_entry_id",sa.Integer(),nullable=False),sa.Column("document_chunk_id",sa.Integer(),nullable=False),
            sa.Column("mapping_type",sa.String(30),nullable=False,server_default="primary"),sa.Column("created_at",sa.DateTime(),nullable=False,server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["catalog_entry_id"],[f"{schema}.recommendation_catalog_entries.id"],ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["document_chunk_id"],[f"{schema}.document_chunks.id"],ondelete="CASCADE"),
            sa.UniqueConstraint("catalog_entry_id","document_chunk_id",name="uq_rccm_entry_chunk"),schema=schema)
    _create_index_if_missing(schema, "ix_rccm_chunk_entry", "recommendation_catalog_chunk_mappings", ["document_chunk_id","catalog_entry_id"])

    existing_tables = set(_inspector(schema).get_table_names(schema=schema))
    if "recommendation_shop_model_states" not in existing_tables:
        op.create_table("recommendation_shop_model_states",
            sa.Column("id",sa.Integer(),primary_key=True),sa.Column("business_id",sa.Integer(),nullable=False),
            sa.Column("algorithm",sa.String(40),nullable=False,server_default="baseline"),sa.Column("model_version",sa.String(120)),
            sa.Column("gate_status",sa.String(20),nullable=False,server_default="baseline"),sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.false()),
            sa.Column("sample_count",sa.Integer(),nullable=False,server_default="0"),sa.Column("consented_customer_count",sa.Integer(),nullable=False,server_default="0"),
            sa.Column("baseline_ndcg",sa.Numeric(10,6)),sa.Column("candidate_ndcg",sa.Numeric(10,6)),sa.Column("baseline_violation_rate",sa.Numeric(10,6)),sa.Column("candidate_violation_rate",sa.Numeric(10,6)),
            sa.Column("train_window",sa.JSON()),sa.Column("holdout_window",sa.JSON()),sa.Column("metrics",sa.JSON()),sa.Column("updated_at",sa.DateTime(),nullable=False,server_default=sa.func.now()),
            sa.UniqueConstraint("business_id",name="uq_rs_model_business"),schema=schema)
    for name, column in (("object_type",sa.String(30)),("recommendation_object_id",sa.String(120)),("catalog_revision",sa.Integer()),("model_version",sa.String(120))):
        columns = {item["name"] for item in _inspector(schema).get_columns("customer_product_interactions", schema=schema)}
        if name not in columns:
            op.add_column("customer_product_interactions", sa.Column(name, column, nullable=(name != "object_type"), server_default=("product" if name == "object_type" else None)), schema=schema)

def downgrade():
    schema = _schema()
    inspector = _inspector(schema)
    if inspector.has_table("customer_product_interactions", schema=schema):
        columns = {item["name"] for item in inspector.get_columns("customer_product_interactions", schema=schema)}
        for name in ("model_version","catalog_revision","recommendation_object_id","object_type"):
            if name in columns:
                op.drop_column("customer_product_interactions",name,schema=schema)
    tables = set(_inspector(schema).get_table_names(schema=schema))
    if "recommendation_shop_model_states" in tables:
        op.drop_table("recommendation_shop_model_states",schema=schema)
    for index_name, table_name in (
        ("ix_rccm_chunk_entry", "recommendation_catalog_chunk_mappings"),
        ("ix_rca_exact_lookup", "recommendation_catalog_attributes"),
        ("ix_rce_shop_sku", "recommendation_catalog_entries"),
        ("ix_rce_shop_type_live", "recommendation_catalog_entries"),
        ("ix_rce_shop_live", "recommendation_catalog_entries"),
    ):
        tables = set(_inspector(schema).get_table_names(schema=schema))
        if table_name in tables:
            indexes = {item["name"] for item in _inspector(schema).get_indexes(table_name, schema=schema)}
            if index_name in indexes:
                op.drop_index(index_name,table_name=table_name,schema=schema)
    tables = set(_inspector(schema).get_table_names(schema=schema))
    for table_name in ("recommendation_catalog_chunk_mappings", "recommendation_catalog_attributes", "recommendation_catalog_entries"):
        if table_name in tables:
            op.drop_table(table_name,schema=schema)
