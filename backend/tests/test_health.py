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
    assert set(body["checks"]) == {"database", "queue", "provider"}
    assert body["checks"]["provider"]["status"] in {"ok", "degraded"}
