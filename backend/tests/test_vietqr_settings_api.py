from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.api.platform_payment_settings import router
from app.auth.platform import require_platform_admin
from app.db.dependencies import get_db
from test_vietqr_checkout import setup

def test_admin_vietqr_configuration_api(setup):
    db, _ = setup
    app = FastAPI(); app.include_router(router, prefix='/api')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_platform_admin] = lambda: object()
    with TestClient(app) as client:
        response = client.get('/api/platform/payment-settings')
        assert response.status_code == 200 and response.json()['provider'] == 'vietqr'
        assert len(response.json()['bank_options']) > 20 and 'api_key' not in response.text
        assert client.post('/api/platform/payment-settings/test').json()['status'] == 'configured'
        body = dict(enabled=True, bank_bin='970407', account_number='0001234', account_name='TEST')
        assert client.put('/api/platform/payment-settings', json=body).json()['bank_name'] == 'Techcombank'
        body['api_key'] = 'SENSITIVE'
        invalid = client.put('/api/platform/payment-settings', json=body)
        assert invalid.status_code == 422 and 'SENSITIVE' not in invalid.text
        def denied(): raise HTTPException(403)
        app.dependency_overrides[require_platform_admin] = denied
        assert client.get('/api/platform/payment-settings').status_code == 403
        assert client.put('/api/platform/payment-settings', json=body).status_code == 403
