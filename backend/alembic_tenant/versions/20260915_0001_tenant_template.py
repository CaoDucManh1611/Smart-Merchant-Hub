"""initial tenant schema template

Revision ID: 20260915_0001
Revises:
"""

from alembic import context, op

from app.database.bases import TenantBase
from app.tenancy.schema import validate_schema_name
import app.models.tenant_template  # noqa: F401


revision = "20260915_0001"
down_revision = None
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
    connection = op.get_bind().execution_options(schema_translate_map={None: schema})
    TenantBase.metadata.create_all(bind=connection)


def downgrade() -> None:
    schema = _schema()
    connection = op.get_bind().execution_options(schema_translate_map={None: schema})
    TenantBase.metadata.drop_all(bind=connection)
