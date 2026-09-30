from sqlalchemy import create_engine, inspect

from app.models import Business


def test_legacy_metadata_fixture_bootstraps_tenant_tables():
    """Legacy SQLite fixtures must include tenant tables after the split."""

    engine = create_engine("sqlite://")
    Business.metadata.create_all(engine)

    assert inspect(engine).has_table("customers")
