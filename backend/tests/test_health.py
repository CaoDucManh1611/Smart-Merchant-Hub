from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_details_reports_safe_component_status():
    response = client.get("/health/details")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert {"database", "queue", "provider", "rate_limit", "ai"}.issubset(body["checks"])
    assert body["checks"]["provider"]["status"] in {"ok", "degraded"}
    assert isinstance(body["alerts"], list)


def test_metrics_is_prometheus_safe():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "crm_database_up" in response.text
    assert "crm_queue_pending_jobs" in response.text
    assert "crm_ai_cost_period" in response.text
