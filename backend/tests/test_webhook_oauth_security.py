import unittest

from app.tenancy.oauth import issue_oauth_state, verify_oauth_state
from app.tenancy.webhook import verify_meta_signature


class WebhookOAuthSecurityTests(unittest.TestCase):
    def test_meta_signature_accepts_only_matching_body(self):
        import hashlib
        import hmac

        body = b'{"entry":[]}'
        digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_meta_signature(body, f"sha256={digest}", "secret"))
        self.assertFalse(verify_meta_signature(body + b"x", f"sha256={digest}", "secret"))

    def test_oauth_state_is_signed_and_contains_tenant(self):
        state = issue_oauth_state(42, "secret")
        self.assertEqual(42, verify_oauth_state(state, "secret")["business_id"])
        with self.assertRaises(PermissionError):
            verify_oauth_state(state + "x", "secret")


if __name__ == "__main__":
    unittest.main()
