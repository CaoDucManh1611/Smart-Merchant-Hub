"""Cross-phase release contracts that must not silently disappear."""

from app.main import app


def _operation_methods() -> dict[str, set[str]]:
    spec = app.openapi()
    return {
        path: {
            method.upper()
            for method in operations
            if method.lower() in {"get", "post", "put", "patch", "delete"}
        }
        for path, operations in spec["paths"].items()
    }


def test_openapi_operation_ids_are_unique():
    operation_ids = [
        operation.get("operationId")
        for operations in app.openapi()["paths"].values()
        for method, operation in operations.items()
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    ]
    duplicates = sorted({item for item in operation_ids if operation_ids.count(item) > 1})
    assert duplicates == []


def test_p0_to_p2_critical_routes_keep_their_http_contracts():
    expected = {
        "/health": {"GET"},
        "/health/details": {"GET"},
        "/health/alerts": {"GET"},
        "/metrics": {"GET"},
        "/api/webhooks/facebook": {"GET", "POST"},
        "/api/webhooks/instagram": {"GET", "POST"},
        "/api/webhooks/telegram": {"POST"},
        "/api/webhooks/zalo": {"POST"},
        "/api/webhooks/{shop_slug}": {"POST"},
        "/api/webhooks/shopee": {"POST"},
        "/api/onboarding/shops": {"POST"},
        "/api/usage": {"GET"},
        "/api/platform/shops/{business_id}/status": {"PATCH"},
        "/api/platform/tenant-schemas/{business_id}": {"POST", "PATCH"},
        "/api/orders/{order_id}/logistics": {"PATCH"},
        "/api/orders/{order_id}/payments": {"POST"},
        "/api/orders/{order_id}/refunds": {"POST"},
        "/api/workflows": {"GET", "POST"},
        "/api/workflows/runs/dispatch": {"POST"},
        "/api/reports/overview.csv": {"GET"},
    }
    actual = _operation_methods()
    mismatches = {
        path: {"expected": methods, "actual": actual.get(path, set())}
        for path, methods in expected.items()
        if not methods.issubset(actual.get(path, set()))
    }
    assert mismatches == {}


def test_dispatch_is_not_a_get_and_shopee_has_no_duplicated_prefix():
    methods = _operation_methods()
    assert "GET" not in methods["/api/workflows/runs/dispatch"]
    assert "/api/webhooks/shopee/webhooks/shopee" not in methods
