import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app.auth.dependencies import issue_token, token_hash
from app.auth.passwords import hash_password
from app.db.dependencies import get_db
from app.main import app
from app.models import Business, User
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.user_email_change import UserEmailChangeChallenge
from app.services.otp_delivery import OtpDeliveryResult


class UserEmailChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Email Change Shop", slug="email-change-shop")
            db.add(business)
            db.flush()
            owner = User(
                business_id=business.id,
                full_name="Owner One",
                email="owner-one@example.test",
                password_hash=hash_password("correct-password"),
                role="owner",
            )
            another = User(
                business_id=business.id,
                full_name="Owner Two",
                email="owner-two@example.test",
                password_hash=hash_password("other-password"),
                role="owner",
            )
            db.add_all([owner, another])
            db.flush()
            cls.business_id = business.id
            cls.owner_id = owner.id
            cls.another_id = another.id
            cls.owner_token, owner_expires = issue_token(owner.id, business_id=business.id, role=owner.role)
            cls.other_token, other_expires = issue_token(another.id, business_id=business.id, role=another.role)
            cls.old_session = AuthSession(
                user_id=owner.id,
                token_hash=token_hash(cls.owner_token),
                expires_at=owner_expires,
                mfa_verified=True,
            )
            second_token, second_expires = issue_token(owner.id, business_id=business.id, role=owner.role)
            cls.other_owner_token = second_token
            db.add_all([
                cls.old_session,
                AuthSession(user_id=owner.id, token_hash=token_hash(second_token), expires_at=second_expires, mfa_verified=True),
                AuthSession(user_id=another.id, token_hash=token_hash(cls.other_token), expires_at=other_expires, mfa_verified=True),
            ])
            db.commit()
            cls.old_session_id = cls.old_session.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def headers(self, token=None):
        return {"Authorization": f"Bearer {token or self.owner_token}"}

    def setUp(self):
        with Session(self.engine) as db:
            db.query(UserEmailChangeChallenge).delete()
            db.query(AuditLog).filter(AuditLog.action.in_(
                ("user_email_change_requested", "user_email_change_delivery_failed", "user_email_changed")
            )).delete(synchronize_session=False)
            db.get(User, self.owner_id).email = "owner-one@example.test"
            db.get(User, self.another_id).email = "owner-two@example.test"
            db.query(AuthSession).filter(AuthSession.user_id == self.owner_id).update(
                {AuthSession.revoked_at: None}, synchronize_session=False
            )
            db.commit()

    @patch("app.api.auth.get_shop_otp_smtp_config", return_value="shop-smtp-config")
    @patch("app.api.auth.deliver_otp", return_value=OtpDeliveryResult(provider="smtp", delivered=True))
    def test_email_changes_only_after_mailbox_otp_and_revokes_other_sessions(self, send_otp, get_smtp_config):
        requested = self.client.post(
            "/api/auth/email-change/request",
            headers=self.headers(),
            json={"new_email": " New.Owner@Example.Test ", "current_password": "correct-password"},
        )
        self.assertEqual(202, requested.status_code, requested.text)
        self.assertEqual("verification_sent", requested.json()["status"])
        self.assertEqual("owner-one@example.test", self._owner_email())
        code = send_otp.call_args.kwargs["code"]
        self.assertEqual("new.owner@example.test", send_otp.call_args.kwargs["destination"])
        self.assertEqual("shop-smtp-config", send_otp.call_args.kwargs["smtp_config"])
        get_smtp_config.assert_called_once_with(ANY, self.business_id)

        wrong_code = "000000" if code != "000000" else "000001"
        wrong = self.client.post("/api/auth/email-change/verify", headers=self.headers(), json={"otp": wrong_code})
        self.assertEqual(422, wrong.status_code)
        self.assertEqual("owner-one@example.test", self._owner_email())

        verified = self.client.post(
            "/api/auth/email-change/verify",
            headers=self.headers(),
            json={"otp": code},
        )
        self.assertEqual(200, verified.status_code, verified.text)
        self.assertEqual("new.owner@example.test", verified.json()["email"])
        self.assertEqual("new.owner@example.test", self._owner_email())
        with Session(self.engine) as db:
            challenge = db.scalar(select(UserEmailChangeChallenge).where(UserEmailChangeChallenge.user_id == self.owner_id))
            self.assertEqual("verified", challenge.status)
            self.assertEqual(2, challenge.attempts)
            sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == self.owner_id)).all()
            revoked = [session for session in sessions if session.id != self.old_session_id]
            self.assertTrue(all(session.revoked_at is not None for session in revoked))
            audit = db.scalar(select(AuditLog).where(AuditLog.action == "user_email_changed"))
            self.assertNotIn("new.owner@example.test", str(audit.metadata_))

    @patch("app.api.auth.deliver_otp", return_value=OtpDeliveryResult(provider="smtp", delivered=True))
    def test_wrong_password_and_another_user_cannot_verify_owner_challenge(self, send_otp):
        rejected = self.client.post(
            "/api/auth/email-change/request",
            headers=self.headers(),
            json={"new_email": "wrong-pass@example.test", "current_password": "incorrect"},
        )
        self.assertEqual(401, rejected.status_code)
        self.assertEqual(0, send_otp.call_count)
        limited = self.client.post(
            "/api/auth/email-change/request",
            headers=self.headers(),
            json={"new_email": "owner-new@example.test", "current_password": "correct-password"},
        )
        self.assertEqual(429, limited.status_code)
        with Session(self.engine) as db:
            failed_attempt = db.scalar(select(UserEmailChangeChallenge).where(
                UserEmailChangeChallenge.user_id == self.owner_id
            ))
            failed_attempt.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=61)
            db.commit()

        requested = self.client.post(
            "/api/auth/email-change/request",
            headers=self.headers(),
            json={"new_email": "owner-new@example.test", "current_password": "correct-password"},
        )
        self.assertEqual(202, requested.status_code, requested.text)
        cross_user = self.client.post(
            "/api/auth/email-change/verify",
            headers=self.headers(self.other_token),
            json={"otp": send_otp.call_args.kwargs["code"]},
        )
        self.assertEqual(422, cross_user.status_code)
        self.assertEqual("owner-one@example.test", self._owner_email())

    @patch("app.api.auth.deliver_otp", return_value=OtpDeliveryResult(provider="in_chat", delivered=True))
    def test_development_chat_fallback_is_not_accepted_as_email_verification(self, _send_otp):
        response = self.client.post(
            "/api/auth/email-change/request",
            headers=self.headers(self.other_token),
            json={"new_email": "owner-two-new@example.test", "current_password": "other-password"},
        )
        self.assertEqual(503, response.status_code)
        self.assertEqual("owner-two@example.test", self._user_email(self.another_id))
        with Session(self.engine) as db:
            challenge = db.scalar(select(UserEmailChangeChallenge).where(UserEmailChangeChallenge.user_id == self.another_id))
            self.assertEqual("delivery_failed", challenge.status)

    @patch("app.api.auth.deliver_otp", return_value=OtpDeliveryResult(provider="smtp", delivered=True))
    def test_email_code_sends_have_cooldown_and_hour_limit(self, send_otp):
        headers = self.headers(self.other_token)
        for attempt in range(5):
            response = self.client.post(
                "/api/auth/email-change/request",
                headers=headers,
                json={"new_email": f"limit-{attempt}@example.test", "current_password": "other-password"},
            )
            self.assertEqual(202, response.status_code, response.text)
            with Session(self.engine) as db:
                latest = db.scalar(select(UserEmailChangeChallenge).where(
                    UserEmailChangeChallenge.user_id == self.another_id
                ).order_by(UserEmailChangeChallenge.id.desc()))
                latest.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=61 * (attempt + 1))
                db.commit()
        limited = self.client.post(
            "/api/auth/email-change/request",
            headers=headers,
            json={"new_email": "limit-extra@example.test", "current_password": "other-password"},
        )
        self.assertEqual(429, limited.status_code, limited.text)
        self.assertEqual(5, send_otp.call_count)

    def _owner_email(self):
        return self._user_email(self.owner_id)

    def _user_email(self, user_id):
        with Session(self.engine) as db:
            return db.get(User, user_id).email


if __name__ == "__main__":
    unittest.main()
