"""Allow validated business profiles beyond scalar setting length."""
from alembic import context,op
import sqlalchemy as sa
from app.tenancy.schema import validate_schema_name
revision="20261025_0014"
down_revision="20261006_0013"
branch_labels=None
depends_on=None

def _schema():
    value=context.config.attributes.get("tenant_schema") or context.get_x_argument(as_dictionary=True).get("tenant_schema")
    if not value: raise RuntimeError("tenant_schema is required")
    return validate_schema_name(str(value))

def upgrade():
    op.alter_column("business_settings","value",existing_type=sa.String(500),type_=sa.Text(),existing_nullable=False,schema=_schema())

def downgrade():
    schema=_schema()
    # PostgreSQL rejects oversized values rather than silently truncating shop configuration.
    op.alter_column("business_settings","value",existing_type=sa.Text(),type_=sa.String(500),existing_nullable=False,schema=schema)
