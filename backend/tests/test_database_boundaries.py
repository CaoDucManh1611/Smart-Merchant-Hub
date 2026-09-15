import pytest
from sqlalchemy import text

from app.database.bases import PlatformBase, TenantBase
from app.database.tenant_session import TenantSessionLocal, tenant_engine, tenant_session
from app.models import platform_control  # noqa: F401
from app.models import tenant_template  # noqa: F401


def test_platform_and_tenant_metadata_are_disjoint():
    platform_tables = set(PlatformBase.metadata.tables)
    tenant_tables = set(TenantBase.metadata.tables)

    assert {"platform_businesses", "tenant_registry", "support_grants"} <= platform_tables
    assert not ({"customers", "messages", "orders", "documents"} & platform_tables)

    assert {"customers", "messages", "orders", "documents"} <= tenant_tables
    assert not ({"platform_businesses", "subscriptions", "platform_memberships", "support_grants"} & tenant_tables)


@pytest.mark.skipif(
    tenant_engine.dialect.name != "postgresql",
    reason="search_path isolation requires PostgreSQL",
)
def test_transaction_local_search_path_does_not_leak_between_sessions():
    with tenant_session("shop_1") as db:
        assert db.execute(text("SHOW search_path")).scalar_one().startswith('"shop_1"')

    with TenantSessionLocal() as db:
        current = db.execute(text("SHOW search_path")).scalar_one()
        assert "shop_1" not in current
