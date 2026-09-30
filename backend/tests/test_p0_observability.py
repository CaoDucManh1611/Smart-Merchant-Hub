from unittest.mock import patch

from app.services.observability import (
    collect_operational_snapshot,
    evaluate_alerts,
    prometheus_text,
)


def _healthy_snapshot() -> dict:
    return {
        "database": {"status": "ok"},
        "queue": {"status": "ok", "pending": 0, "running": 0, "failed": 0},
        "provider": {"status": "ok", "circuits": {}},
        "rate_limit": {"backend": "redis", "status": "ok"},
        "ai": {"status": "ok", "cost": 0.0, "period_start": "2026-09-01T00:00:00"},
    }


def test_alerts_fire_for_every_p0_operational_failure():
    snapshot = _healthy_snapshot()
    snapshot["database"] = {"status": "error", "error_type": "OperationalError"}
    snapshot["queue"].update(pending=100, failed=2)
    snapshot["provider"] = {
        "status": "degraded",
        "circuits": {"zalo": {"state": "open", "failures": 5}},
    }
    snapshot["rate_limit"]["status"] = "error"
    snapshot["ai"]["cost"] = 50.0

    names = {item["name"] for item in evaluate_alerts(snapshot)}

    assert names == {
        "database_unavailable",
        "queue_backlog",
        "queue_failed_jobs",
        "provider_circuit_open",
        "shared_rate_limit_unavailable",
        "ai_cost_threshold",
    }


def test_alert_threshold_boundaries_do_not_fire_early():
    snapshot = _healthy_snapshot()
    snapshot["queue"]["pending"] = 99
    snapshot["ai"]["cost"] = 49.9999

    assert evaluate_alerts(snapshot) == []


def test_database_failure_snapshot_never_exposes_exception_message():
    class BrokenDatabase:
        def execute(self, _statement):
            raise RuntimeError("postgresql://admin:secret-password@db/private")

    with patch("app.services.observability.provider_breaker_snapshot", return_value={}):
        snapshot = collect_operational_snapshot(BrokenDatabase())

    rendered = str(snapshot)
    assert snapshot["database"] == {"status": "error", "error_type": "RuntimeError"}
    assert "secret-password" not in rendered
    assert "postgresql://" not in rendered


def test_redis_health_failure_becomes_a_firing_alert():
    class UnavailableRedis:
        def __init__(self, _url):
            pass

        def ping(self):
            return False

    class MinimalDatabase:
        def execute(self, _statement):
            return None

        def query(self, _model):
            raise RuntimeError("stop after connectivity check")

    # Isolate Redis behavior from the later database-backed counters.
    with patch("app.services.observability.settings.RATE_LIMIT_ENABLED", True), patch(
        "app.services.observability.settings.RATE_LIMIT_BACKEND", "redis"
    ), patch("app.services.observability.settings.REDIS_URL", "redis://redis:6379/0"), patch(
        "app.middleware.security.RedisRateLimiter", UnavailableRedis
    ), patch("app.services.observability.provider_breaker_snapshot", return_value={}):
        snapshot = collect_operational_snapshot(MinimalDatabase())

    assert snapshot["rate_limit"]["status"] == "error"
    assert "shared_rate_limit_unavailable" in {
        item["name"] for item in evaluate_alerts(snapshot)
    }


def test_prometheus_payload_has_fixed_safe_metrics_only():
    snapshot = _healthy_snapshot()
    snapshot["queue"].update(pending=7, running=2, failed=1)
    snapshot["ai"]["cost"] = 12.3456
    snapshot["provider"]["circuits"] = {
        "provider-secret-name": {"state": "closed", "failures": 0}
    }

    payload = prometheus_text(snapshot)

    assert "crm_queue_pending_jobs 7" in payload
    assert "crm_ai_cost_period 12.3456" in payload
    assert "provider-secret-name" not in payload
    assert "{" not in payload
