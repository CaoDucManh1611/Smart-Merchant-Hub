import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.bases import PlatformBase
from app.models.business import User
from app.models.platform_control import PlatformBusiness, TenantRegistry
from app.tenancy.context import resolve_tenant_context
from app.tenancy.dependencies import get_authenticated_tenant


def test_authenticated_tenant_requires_active_registry_and_returns_server_schema():
    engine = create_engine("sqlite://")
    PlatformBase.metadata.create_all(engine)
    user = User(id=9, business_id=42, full_name="Agent", email="agent@test", role="agent")
    with Session(engine) as db:
        db.add(PlatformBusiness(id=42, name="Shop", slug="shop-42"))
        db.commit()
        with pytest.raises(Exception) as missing:
            get_authenticated_tenant(user=user, platform_db=db)
        assert "tenant_unprovisioned" in str(missing.value)
        db.add(TenantRegistry(business_id=42, schema_name="shop_42", state="active", feature_enabled=True, tenant_revision="head"))
        db.commit()
        context = get_authenticated_tenant(user=user, platform_db=db)
        assert context.business_id == 42
        assert context.schema_name == "shop_42"
        assert context.user_id == 9


def test_tenant_context_ignores_foreign_header_when_authenticated():
    context = resolve_tenant_context(authenticated_business_id=42, development_header="43", environment="development")
    assert context.business_id == 42
    assert context.source == "authenticated_user"
