from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.platform_otp_email import router
from app.auth.dependencies import get_current_user
from app.auth.platform import require_platform_admin
from app.db.dependencies import get_db
from app.models.setting import AppSetting
from app.services import platform_otp_email as service
from app.services.otp_delivery import OtpDeliveryError, OtpDeliveryResult


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    AppSetting.__table__.create(engine)
    with Session(engine) as db:
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[require_platform_admin] = lambda: object()
        monkeypatch.setattr(service.settings, "CHANNEL_ENCRYPTION_KEY", "test-only-key")
        yield TestClient(app), db
    engine.dispose()


def payload(**changes):
    return {"enabled": True, "username": "sender@gmail.com", "from_email": "sender@gmail.com",
            "from_name": "Merchant Hub", "password": "test-app-password", **changes}


def test_encrypted_save_redacted_get_and_blank_password_retention(setup):
    client, db = setup
    response = client.put("/api/platform/otp-email", json=payload())
    assert response.status_code == 200, response.text
    row = db.get(AppSetting, "platform.otp.smtp.password_encrypted")
    encrypted = row.value
    assert encrypted != "test-app-password" and "test-app-password" not in response.text
    assert response.json()["password_configured"] is True
    assert "password" not in response.json()
    assert client.put("/api/platform/otp-email", json=payload(password="")).status_code == 200
    assert row.value == encrypted
    assert service.get_platform_otp_smtp_config(db).password == "test-app-password"
    assert client.get("/api/platform/otp-email").json() == response.json()


@pytest.mark.parametrize("changes", [{"host": "localhost"}, {"port": 465}, {"security": "ssl"},
    {"username": "attacker@example.com"}, {"from_email": "other@gmail.com"}, {"from_name": "bad\r\nheader"}])
def test_gmail_settings_reject_unsafe_values(setup, changes):
    client, db = setup
    assert client.put("/api/platform/otp-email", json=payload(**changes)).status_code == 422
    assert db.query(AppSetting).count() == 0


def test_routes_require_authentication_and_platform_admin(setup):
    client, db = setup
    client.app.dependency_overrides.pop(require_platform_admin)
    for method, path, body in [("GET", "/api/platform/otp-email", None),
        ("PUT", "/api/platform/otp-email", payload()),
        ("POST", "/api/platform/otp-email/test", {"email": "recipient@example.test"})]:
        assert client.request(method, path, json=body).status_code == 401
    client.app.dependency_overrides[get_current_user] = lambda: Mock(id=123)
    # No platform membership exists; use the same isolated DB for auth's legacy dependency.
    from app.db.dependencies import get_db
    from app.models.saas import PlatformMembership
    PlatformMembership.__table__.create(db.bind)
    client.app.dependency_overrides[get_db] = lambda: db
    assert client.get("/api/platform/otp-email").status_code == 403
    assert client.put("/api/platform/otp-email", json=payload()).status_code == 403
    assert client.post("/api/platform/otp-email/test", json={"email": "recipient@example.test"}).status_code == 403


def test_test_email_uses_validated_recipient_and_saved_smtp(setup, monkeypatch):
    client, db = setup
    client.put("/api/platform/otp-email", json=payload())
    delivery = Mock(return_value=OtpDeliveryResult(provider="smtp", delivered=True))
    monkeypatch.setattr("app.api.platform_otp_email.send_smtp_test_email", delivery)
    response = client.post("/api/platform/otp-email/test", json={"email": "recipient@example.test"})
    assert response.status_code == 200
    assert response.json() == {"status": "smtp_accepted", "email": "recipient@example.test"}
    assert delivery.call_args.kwargs["destination"] == "recipient@example.test"
    assert delivery.call_args.kwargs["smtp_config"].host == "smtp.gmail.com"
    assert client.post("/api/platform/otp-email/test", json={"email": "bad\r\nBcc: attacker"}).status_code == 422
    db.get(AppSetting, service.PREFIX + "last_test_at").value = "0"
    db.commit()
    delivery.side_effect = OtpDeliveryError("private provider diagnostics")
    response = client.post("/api/platform/otp-email/test", json={"email": "recipient@example.test"})
    assert response.status_code == 503 and "private" not in response.text


def test_saved_override_uses_smtp_despite_disabled_environment(setup, monkeypatch):
    client, db = setup
    client.put("/api/platform/otp-email", json=payload())
    from app.services import otp_delivery
    monkeypatch.setattr(otp_delivery.settings, "OTP_DELIVERY_MODE", "disabled")
    smtp = Mock()
    monkeypatch.setattr(otp_delivery, "_send_smtp", smtp)
    config = service.get_platform_otp_smtp_config(db)
    result = otp_delivery.deliver_otp(channel="email", destination="recipient@example.test", code="123456", smtp_config=config)
    assert result.provider == "smtp" and result.delivered
    assert smtp.call_args.kwargs["smtp_config"].password == "test-app-password"


@pytest.mark.parametrize("failure", [False, True])
def test_signup_uses_global_override_and_rolls_back_on_smtp_failure(setup, monkeypatch, failure):
    client, db = setup
    client.put("/api/platform/otp-email", json=payload(password_configured=True))
    from app.api.onboarding import router as signup_router
    from app.models.business import User
    from app.models.signup import SignupEmailChallenge
    from app.services import otp_delivery
    User.__table__.create(db.bind)
    SignupEmailChallenge.__table__.create(db.bind)
    client.app.include_router(signup_router, prefix="/api")
    monkeypatch.setattr(otp_delivery.settings, "OTP_DELIVERY_MODE", "disabled")
    # Even a configured development fallback cannot establish mailbox delivery.
    monkeypatch.setattr(otp_delivery.settings, "OTP_DELIVERY_FALLBACK", "in_chat")
    smtp = Mock(side_effect=OtpDeliveryError("private error") if failure else None)
    monkeypatch.setattr(otp_delivery, "_send_smtp", smtp)
    response = client.post("/api/onboarding/signup/request", json={"email": "signup@example.test"})
    assert response.status_code == (503 if failure else 202), response.text
    assert db.query(SignupEmailChallenge).count() == (0 if failure else 1)
    assert db.query(User).count() == 0
    assert smtp.call_args.kwargs["smtp_config"].username == "sender@gmail.com"
    assert smtp.call_args.kwargs["destination"] == "signup@example.test"


def test_defaults_disabled_sender_and_missing_password(setup, monkeypatch):
    client, db = setup
    assert client.get("/api/platform/otp-email").json()["from_name"] == "Smart Merchant Hub"
    assert client.put("/api/platform/otp-email", json=payload(password="")).status_code == 422
    assert db.query(AppSetting).count() == 0
    assert client.post("/api/platform/otp-email/test", json={"email": "recipient@example.test"}).status_code == 503


@pytest.mark.parametrize("changes", [{"password": "sensitive-password" * 30},
    {"username": "not-gmail"}, {"from_email": "different@gmail.com"}, {"from_name": "bad\r\nheader"}, {"host": "localhost"}])
def test_validation_never_echoes_password(setup, changes):
    client, db = setup
    body = payload(**changes)
    response = client.put("/api/platform/otp-email", json=body)
    assert response.status_code == 422
    assert body["password"] not in response.text
    assert "input" not in response.text and "password_encrypted" not in response.text


@pytest.mark.parametrize("failure", [False, True])
def test_password_reset_uses_global_sender(setup, monkeypatch, failure):
    client, db = setup
    client.put("/api/platform/otp-email", json=payload())
    from app.api.auth import router as auth_router
    from app.models.business import Business, User
    from app.models.signup import SignupEmailChallenge
    from app.services import otp_delivery
    Business.__table__.create(db.bind)
    User.__table__.create(db.bind)
    SignupEmailChallenge.__table__.create(db.bind)
    business = Business(name="Isolated reset", slug="isolated-reset")
    db.add(business)
    db.flush()
    db.add(User(business_id=business.id, full_name="Test", email="reset@example.test", role="owner"))
    db.commit()
    client.app.include_router(auth_router, prefix="/api")
    monkeypatch.setattr(otp_delivery.settings, "OTP_DELIVERY_MODE", "disabled")
    monkeypatch.setattr(otp_delivery.settings, "OTP_DELIVERY_FALLBACK", "in_chat")
    smtp = Mock(side_effect=OtpDeliveryError("private") if failure else None)
    monkeypatch.setattr(otp_delivery, "_send_smtp", smtp)
    response = client.post("/api/auth/password-reset/request", json={"email": "reset@example.test"})
    assert response.status_code == 202, response.text
    challenge = db.query(SignupEmailChallenge).one()
    assert challenge.status == ("delivery_failed" if failure else "pending")
    assert smtp.call_args.kwargs["smtp_config"].username == "sender@gmail.com"


def test_test_email_throttles_all_recipients_and_failed_attempts(setup, monkeypatch):
    client, db = setup
    client.put("/api/platform/otp-email", json=payload())
    delivery = Mock(side_effect=OtpDeliveryError("failure"))
    monkeypatch.setattr("app.api.platform_otp_email.send_smtp_test_email", delivery)
    assert client.post("/api/platform/otp-email/test", json={"email": "one@example.test"}).status_code == 503
    response = client.post("/api/platform/otp-email/test", json={"email": "two@example.test"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert delivery.call_count == 1
    db.get(AppSetting, service.PREFIX + "last_test_at").value = "0"
    db.commit()
    assert client.post("/api/platform/otp-email/test", json={"email": "two@example.test"}).status_code == 503
    assert delivery.call_count == 2
