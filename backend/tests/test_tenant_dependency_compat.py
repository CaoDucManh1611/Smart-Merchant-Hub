from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.platform_session import get_platform_db
from app.core.config import settings
from app.db.dependencies import get_db
from app.main import app
from app.tenancy.context import TenantContext
from app.tenancy.crm_session import get_tenant_db


def test_test_mode_tenant_dependency_reuses_overridden_legacy_session(monkeypatch):
    engine = create_engine("sqlite://")
    session = Session(engine)
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")

    yielded = next(get_tenant_db(TenantContext(7, "test"), session))

    assert yielded is session
    assert yielded.info["business_id"] == 7
    session.close()


def test_test_mode_platform_dependency_reuses_get_db_override(monkeypatch):
    engine = create_engine("sqlite://")
    session = Session(engine)

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    try:
        yielded = next(get_platform_db())
        assert yielded is session
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
