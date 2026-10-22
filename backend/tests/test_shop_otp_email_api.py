from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.workspace import router
from app.auth.dependencies import require_admin_access
from app.core.config import settings
from app.db.dependencies import get_db
from app.models.business_setting import BusinessSetting
from app.services.shop_otp_email import save_shop_otp_email
from app.tenancy.context import TenantContext
from app.tenancy.crm_session import get_tenant_db
from app.tenancy.dependencies import get_tenant_context


def test_shop_smtp_test_uses_saved_config_and_reports_acceptance(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    BusinessSetting.__table__.create(engine)
    with Session(engine) as db:
        monkeypatch.setattr(settings, "CHANNEL_ENCRYPTION_KEY", "test-key")
        save_shop_otp_email(db, 21, {
            "enabled": True, "host": "smtp.example.test", "port": 587, "security": "starttls",
            "username": "sender@example.test", "password": "test-password",
            "from_email": "sender@example.test", "from_name": "Test Shop",
        })
        db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[get_tenant_db] = lambda: db
        app.dependency_overrides[get_tenant_context] = lambda: TenantContext(business_id=21, source="test")
        app.dependency_overrides[require_admin_access] = lambda: SimpleNamespace(id=7)
        app.dependency_overrides[get_db] = lambda: db
        delivery = Mock()
        monkeypatch.setattr("app.api.workspace.send_smtp_test_email", delivery)
        monkeypatch.setattr("app.api.workspace.record_audit", Mock())
        client = TestClient(app)

        response = client.post("/api/workspace/otp-email/test", json={"email": "Test@Example.Test"})
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "smtp_accepted", "email": "test@example.test"}
        assert delivery.call_args.kwargs["destination"] == "test@example.test"
        assert delivery.call_args.kwargs["smtp_config"].host == "smtp.example.test"
        assert client.post("/api/workspace/otp-email/test", json={"email": "other@example.test"}).status_code == 429
        assert delivery.call_count == 1
    engine.dispose()


def test_shop_smtp_settings_survive_reload_without_returning_the_password(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    BusinessSetting.__table__.create(engine)
    with Session(engine) as db:
        monkeypatch.setattr(settings, "CHANNEL_ENCRYPTION_KEY", "test-key")
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[get_tenant_db] = lambda: db
        app.dependency_overrides[get_tenant_context] = lambda: TenantContext(business_id=21, source="test")
        app.dependency_overrides[require_admin_access] = lambda: SimpleNamespace(id=7)
        app.dependency_overrides[get_db] = lambda: db
        monkeypatch.setattr("app.api.workspace.record_audit", Mock())
        client = TestClient(app)

        saved = client.put("/api/workspace/otp-email", json={
            "enabled": True,
            "host": "smtp.gmail.com",
            "port": 587,
            "security": "starttls",
            "username": "info@gmail.com",
            "password": "google-app-password",
            "from_email": "info@gmail.com",
            "from_name": "Shop Merchant",
        })
        assert saved.status_code == 200, saved.text
        assert saved.json()["enabled"] is True
        assert saved.json()["password_configured"] is True
        assert "password" not in saved.json()

        reopened = client.get("/api/workspace/otp-email")
        assert reopened.status_code == 200, reopened.text
        assert reopened.json() == {
            "enabled": True,
            "host": "smtp.gmail.com",
            "port": 587,
            "security": "starttls",
            "username": "info@gmail.com",
            "from_email": "info@gmail.com",
            "from_name": "Shop Merchant",
            "password_configured": True,
        }
        assert "password" not in reopened.json()
    engine.dispose()
