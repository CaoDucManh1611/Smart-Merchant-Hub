import pytest
from sqlalchemy import inspect, text

from app.database.tenant_session import tenant_engine
from app.models.tenant_template import TENANT_TABLE_NAMES
from app.tenancy.migration_runner import current_tenant_revision, upgrade_tenant_schema
from app.tenancy.schema import schema_name_for, validate_schema_name


def test_schema_name_is_server_generated_and_strict():
    assert schema_name_for(42) == "shop_42"
    for invalid in ("shop_0", "tenant_42", "shop_1;drop schema public", "shop_-1", "public"):
        with pytest.raises(ValueError):
            validate_schema_name(invalid)


@pytest.mark.skipif(
    tenant_engine.dialect.name != "postgresql",
    reason="tenant schema migrations require PostgreSQL",
)
def test_two_tenant_schemas_upgrade_independently_and_idempotently():
    schemas = ("shop_91001", "shop_91002")
    with tenant_engine.connect() as connection:
        if connection.dialect.name != "postgresql":
            pytest.skip("tenant schema migration requires PostgreSQL schemas")
        try:
            for schema in schemas:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            connection.commit()

            first_revision = upgrade_tenant_schema(connection, schemas[0])
            connection.commit()
            second_revision = upgrade_tenant_schema(connection, schemas[1])
            connection.commit()
            repeated_revision = upgrade_tenant_schema(connection, schemas[0])
            connection.commit()

            assert first_revision == second_revision == repeated_revision == "20260923_0003"
            assert current_tenant_revision(connection, schemas[0]) == "20260923_0003"
            assert current_tenant_revision(connection, schemas[1]) == "20260923_0003"

            inspector = inspect(connection)
            expected = set(TENANT_TABLE_NAMES) | {"alembic_version"}
            assert expected <= set(inspector.get_table_names(schema=schemas[0]))
            assert expected <= set(inspector.get_table_names(schema=schemas[1]))
        finally:
            connection.rollback()
            for schema in schemas:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            connection.commit()
