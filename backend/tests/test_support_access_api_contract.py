from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_support_api_exposes_owner_grant_revoke_and_session_routes():
    source = (ROOT / "app" / "api" / "support.py").read_text(encoding="utf-8")
    assert '"/support/grants"' in source
    assert '"/support/grants/{grant_id}/revoke"' in source
    assert '"/platform/support-sessions"' in source
    assert "get_current_user" in source
    assert "get_platform_db" in source
    assert "mfa_required" in source


def test_support_tokens_are_scope_bound_and_content_scopes_do_not_exist():
    source = (ROOT / "app" / "services" / "support_access.py").read_text(encoding="utf-8")
    assert '"conversation:read"' in source
    assert "DENIED_CONTENT_SCOPES" in source
    assert "revoked_at" in source
    assert "support_access_allowed" in source
    assert "support_access_denied" in source
