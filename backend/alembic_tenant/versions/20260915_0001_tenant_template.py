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
    return validate_schema_name(str(context.config.attributes["tenant_schema"]))


def upgrade() -> None:
    schema = _schema()
    connection = op.get_bind().execution_options(schema_translate_map={None: schema})
    TenantBase.metadata.create_all(bind=connection)


def downgrade() -> None:
    schema = _schema()
    connection = op.get_bind().execution_options(schema_translate_map={None: schema})
    TenantBase.metadata.drop_all(bind=connection)
