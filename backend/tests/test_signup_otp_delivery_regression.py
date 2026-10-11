from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import onboarding
from app.db.dependencies import get_db
from app.models.business import User
from app.models.signup import SignupEmailChallenge
from app.models.setting import AppSetting
from app.services.otp_delivery import OtpDeliveryResult


@pytest.mark.parametrize("provider,delivered,expected", [
    ("in_chat", True, 503), ("disabled", True, 503), ("twilio", True, 503),
    ("smtp", False, 503), ("smtp", True, 202),
])
def test_signup_requires_successful_smtp_delivery(monkeypatch, provider, delivered, expected):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    User.__table__.create(engine)
    AppSetting.__table__.create(engine)
    SignupEmailChallenge.__table__.create(engine)
    delivery = Mock(return_value=OtpDeliveryResult(provider=provider, delivered=delivered))
    monkeypatch.setattr(onboarding, "deliver_otp", delivery)
    app = FastAPI()
    app.include_router(onboarding.router, prefix="/api")

    def isolated_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    try:
        with TestClient(app) as client:
            response = client.post("/api/onboarding/signup/request", json={"email": "signup-regression@example.test"})
        assert response.status_code == expected, response.text
        with Session(engine) as db:
            assert db.query(User).count() == 0
            assert db.query(SignupEmailChallenge).count() == (1 if expected == 202 else 0)
        if expected == 202:
            assert response.json()["status"] == "otp_sent"
        else:
            assert "status" not in response.json()
        assert delivery.call_args.kwargs["channel"] == "email"
        assert delivery.call_args.kwargs["destination"] == "signup-regression@example.test"
    finally:
        engine.dispose()
