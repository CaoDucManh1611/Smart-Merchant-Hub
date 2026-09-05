import io
import logging
import unittest

from app.core.logging import RedactingFilter, redact_secrets
from app.middleware.security import RateLimitMiddleware


class SecurityHardeningTests(unittest.TestCase):
    def test_secret_redaction_never_returns_credential_value(self):
        message = redact_secrets("access_token=super-secret database_url=postgres://u:p@db/crm")
        self.assertNotIn("super-secret", message)
        self.assertNotIn("postgres://u:p@db/crm", message)
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

    def test_rate_limit_defaults_are_positive(self):
        middleware = RateLimitMiddleware(
            lambda scope, receive, send: None,
            enabled=True,
            max_requests=2,
            window_seconds=60,
        )
        self.assertEqual(2, middleware.max_requests)
        self.assertEqual(60, middleware.window_seconds)


if __name__ == "__main__":
    unittest.main()
