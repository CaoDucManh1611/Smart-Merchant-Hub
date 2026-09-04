import unittest

from app.tenancy.context import TenantContext, resolve_tenant_context


class TenantContextTests(unittest.TestCase):
    def test_authenticated_user_takes_precedence_over_development_header(self):
        context = resolve_tenant_context(
            authenticated_business_id=7,
            development_header="9",
            environment="development",
        )
        self.assertEqual(TenantContext(7, "authenticated_user"), context)

    def test_channel_account_is_trusted_source(self):
        context = resolve_tenant_context(channel_business_id=11, environment="production")
        self.assertEqual(TenantContext(11, "channel_account"), context)

    def test_development_header_is_rejected_in_production(self):
        with self.assertRaises(PermissionError):
            resolve_tenant_context(development_header="7", environment="production")

    def test_missing_context_has_no_default_fallback(self):
        with self.assertRaises(PermissionError):
            resolve_tenant_context(environment="development")

    def test_conflicting_trusted_sources_are_rejected(self):
        with self.assertRaises(PermissionError):
            resolve_tenant_context(
                authenticated_business_id=7,
                channel_business_id=8,
                environment="production",
            )


if __name__ == "__main__":
    unittest.main()
