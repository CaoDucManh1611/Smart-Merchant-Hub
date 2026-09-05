import io
import logging
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import require_admin_access, require_write_access
from app.core.config import Settings
from app.core.logging import RedactingFilter, redact_secrets
from app.middleware.security import RateLimitMiddleware, SecurityHeadersMiddleware
from app.services.meta_errors import MetaAPIError
from app.services.message_service import process_and_save_message


class SecurityHardeningTests(unittest.TestCase):
    def test_secret_redaction_never_returns_credential_value(self):
        message = redact_secrets(
            'access_token=super-secret database_url=postgres://u:p@db/crm '
            '{"refresh_token":"json-secret"}'
        )
        self.assertNotIn("super-secret", message)
        self.assertNotIn("postgres://u:p@db/crm", message)
        self.assertNotIn("json-secret", message)
        self.assertIn("[REDACTED]", message)

    def test_logging_filter_handles_formatted_arguments(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(RedactingFilter())
        logger = logging.getLogger("security-hardening-test")
        logger.handlers[:] = [handler]
        logger.propagate = False
        logger.warning("Authorization: Bearer %s", "secret-token")
        self.assertNotIn("secret-token", stream.getvalue())

    def test_logging_filter_redacts_exception_text(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(RedactingFilter())
        logger = logging.getLogger("security-hardening-exception-test")
        logger.handlers[:] = [handler]
        logger.propagate = False
        try:
            raise RuntimeError("access_token=exception-secret")
        except RuntimeError:
            logger.exception("Provider call failed")
        self.assertNotIn("exception-secret", stream.getvalue())

    def test_rate_limit_defaults_are_positive(self):
        middleware = RateLimitMiddleware(
            lambda scope, receive, send: None,
            enabled=True,
            max_requests=2,
            window_seconds=60,
        )
        self.assertEqual(2, middleware.max_requests)
        self.assertEqual(60, middleware.window_seconds)

    def test_rate_limit_returns_429_after_the_configured_limit(self):
        app = FastAPI()

        @app.get("/api/ping")
        def ping():
            return {"ok": True}

        app.add_middleware(
            RateLimitMiddleware,
            enabled=True,
            max_requests=2,
            window_seconds=60,
        )
        client = TestClient(app)
        self.assertEqual(200, client.get("/api/ping").status_code)
        self.assertEqual(200, client.get("/api/ping").status_code)
        limited = client.get("/api/ping")
        self.assertEqual(429, limited.status_code)
        self.assertEqual("2", limited.headers["X-RateLimit-Limit"])
        self.assertEqual("0", limited.headers["X-RateLimit-Remaining"])
        self.assertIn("Retry-After", limited.headers)

    def test_security_headers_include_hsts_when_enabled(self):
        app = FastAPI()

        @app.get("/health")
        def health():
            return {"ok": True}

        app.add_middleware(SecurityHeadersMiddleware, hsts_enabled=True)
        response = TestClient(app).get("/health")
        self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
        self.assertEqual("DENY", response.headers["X-Frame-Options"])
        self.assertIn("max-age=31536000", response.headers["Strict-Transport-Security"])

    def test_production_rejects_an_unbound_inbound_message(self):
        db = Mock()
        with patch("app.services.message_service.settings.ENVIRONMENT", "production"):
            saved = process_and_save_message(
                db,
                {
                    "channel": "facebook",
                    "external_user_id": "customer-1",
                    "external_message_id": "message-1",
                },
            )
        self.assertFalse(saved)
        db.execute.assert_not_called()

    def test_production_requires_login_for_write_and_admin_dependencies(self):
        with patch("app.auth.dependencies.settings.ENVIRONMENT", "production"):
            with self.assertRaises(HTTPException) as write_error:
                require_write_access(None)
            with self.assertRaises(HTTPException) as admin_error:
                require_admin_access(None)
        self.assertEqual(401, write_error.exception.status_code)
        self.assertEqual(401, admin_error.exception.status_code)

    def test_production_configuration_requires_https_redirect_and_hsts(self):
        config = Settings(
            DATABASE_URL="postgresql://user:password@db.example/crm",
            ENVIRONMENT="production",
            AUTH_SECRET="a" * 32,
            CHANNEL_ENCRYPTION_KEY="b" * 32,
            CORS_ORIGINS="https://crm.example.com",
            ALLOWED_HOSTS="api.example.com",
            PUBLIC_BASE_URL="https://api.example.com",
            FRONTEND_BASE_URL="https://crm.example.com",
            FACEBOOK_VERIFY_TOKEN="verify-token",
            RATE_LIMIT_ENABLED=True,
            FORCE_HTTPS=False,
            HSTS_ENABLED=False,
        )
        with self.assertRaisesRegex(RuntimeError, "FORCE_HTTPS.*HSTS_ENABLED"):
            config.validate_runtime()

    def test_provider_error_detail_does_not_expose_the_raw_response(self):
        error = MetaAPIError(
            channel="facebook",
            stage="send",
            response={"error": {"message": "Không gửi được", "access_token": "provider-secret"}},
        )
        detail = error.to_detail()
        self.assertNotIn("response", detail)
        self.assertNotIn("provider-secret", str(detail))


if __name__ == "__main__":
    unittest.main()
