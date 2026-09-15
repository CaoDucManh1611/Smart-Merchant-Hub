from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.passwords import hash_password
from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business, User
from app.models.saas import SupportGrant


def test_owner_grant_issues_scoped_session_and_revocation_is_immediate():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Business.metadata.create_all(engine)
    with Session(engine) as db:
        shop = Business(name="Support shop", slug="support-shop")
        db.add(shop)
        db.flush()
        owner = User(business_id=shop.id, full_name="Owner", email="owner-support@test", role="owner", password_hash=hash_password("password"))
        support = User(business_id=shop.id, full_name="Support", email="support@test", role="support", password_hash=hash_password("password"))
        db.add_all([owner, support])
        db.commit()
        shop_id, support_id = shop.id, support.id

    def override_get_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        owner_login = client.post("/api/auth/login", json={"email": "owner-support@test", "password": "password"})
        assert owner_login.status_code == 200, owner_login.text
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}
        grant_response = client.post(
            "/api/support/grants",
            headers=owner_headers,
            json={
                "support_user_id": support_id,
                "reason": "Diagnose webhook delivery",
                "scopes": ["channels:diagnose", "settings:read"],
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            },
        )
        assert grant_response.status_code == 201, grant_response.text
        grant_id = grant_response.json()["id"]

        support_login = client.post("/api/auth/login", json={"email": "support@test", "password": "password"})
        assert support_login.status_code == 200, support_login.text
        support_headers = {"Authorization": f"Bearer {support_login.json()['access_token']}"}
        session = client.post("/api/platform/support-sessions", headers=support_headers, json={"grant_id": grant_id})
        assert session.status_code == 200, session.text
        scoped_headers = {"Authorization": f"Bearer {session.json()['access_token']}"}
        assert client.get("/api/support/health", headers=scoped_headers).status_code == 200
        # A support token can never fall through to ordinary customer APIs.
        assert client.get("/api/customers", headers=scoped_headers).status_code == 403

        revoked = client.post(f"/api/support/grants/{grant_id}/revoke", headers=owner_headers)
        assert revoked.status_code == 200, revoked.text
        assert client.get("/api/support/health", headers=scoped_headers).status_code == 403
        with Session(engine) as db:
            assert db.get(SupportGrant, grant_id).revoked_at is not None
    finally:
        app.dependency_overrides.clear()
