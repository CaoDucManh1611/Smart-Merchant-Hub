import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.passwords import hash_password
from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business, User


class AuthApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Auth One", slug="auth-one")
            db.add(business)
            db.flush()
            owner = User(
                business_id=business.id,
                full_name="Owner",
                email="owner@auth.test",
                role="owner",
                password_hash=hash_password("correct horse battery staple"),
            )
            viewer = User(
                business_id=business.id,
                full_name="Viewer",
                email="viewer@auth.test",
                role="viewer",
                password_hash=hash_password("viewer-password"),
            )
            db.add_all([owner, viewer])
            db.commit()
            cls.business_id = business.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def login(self, email="owner@auth.test", password="correct horse battery staple"):
        response = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_id)},
            json={"email": email, "password": password},
        )
        self.assertEqual(200, response.status_code)
        return response.json()

    def test_login_me_and_logout_revokes_token(self):
        body = self.login()
        token = body["access_token"]
        headers = {"Authorization": f"Bearer {token}", "X-Business-Id": str(self.business_id)}
        me = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(200, me.status_code)
        self.assertEqual("owner@auth.test", me.json()["email"])
        self.assertEqual(204, self.client.post("/api/auth/logout", headers=headers).status_code)
        self.assertEqual(401, self.client.get("/api/auth/me", headers=headers).status_code)

    def test_invalid_password_and_missing_token_are_rejected(self):
        invalid = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_id)},
            json={"email": "owner@auth.test", "password": "wrong"},
        )
        self.assertEqual(401, invalid.status_code)
        self.assertEqual(401, self.client.get("/api/auth/me").status_code)

    def test_audit_log_is_admin_only_and_redacted(self):
        body = self.login()
        headers = {"Authorization": f"Bearer {body['access_token']}", "X-Business-Id": str(self.business_id)}
        logs = self.client.get("/api/auth/audit-logs", headers=headers)
        self.assertEqual(200, logs.status_code)
        self.assertTrue(logs.json())
        self.assertNotIn("correct horse battery staple", str(logs.json()))

        viewer = self.login("viewer@auth.test", "viewer-password")
        viewer_headers = {"Authorization": f"Bearer {viewer['access_token']}", "X-Business-Id": str(self.business_id)}
        self.assertEqual(403, self.client.get("/api/auth/audit-logs", headers=viewer_headers).status_code)


if __name__ == "__main__":
    unittest.main()
