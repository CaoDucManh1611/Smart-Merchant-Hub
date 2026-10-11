from unittest.mock import Mock
from datetime import datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.platform_payment_settings import PaymentValidationRoute
from fastapi import APIRouter, Depends
from app.auth.platform import require_platform_admin
from app.db.dependencies import get_db
from app.models.setting import AppSetting
from app.models.business import Business
from app.models.subscription_payment_attempt import SubscriptionPaymentAttempt
from app.services import platform_payment_settings as service

# Preserve legacy payOS service coverage; the production admin API now uses VietQR.
router = APIRouter(prefix='/platform/payment-settings', route_class=PaymentValidationRoute,
                   dependencies=[Depends(require_platform_admin)])
@router.get('')
def legacy_read(db=Depends(get_db)):
    return service.read(db)
@router.put('')
def legacy_save(payload: service.PaymentSettingsUpdate, db=Depends(get_db)):
    try:
        result = service.save(db, payload); db.commit(); return result
    except ValueError:
        db.rollback(); raise HTTPException(422, 'Invalid legacy settings')
@router.post('/test')
def legacy_check(db=Depends(get_db)):
    from app.services.subscription_payment_service import get_client
    get_client(service.resolve(db, require_enabled=True))
    return {'status': 'configured'}


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Business.metadata.create_all(engine)
    with Session(engine) as db:
        app = FastAPI()
        app.include_router(router, prefix='/api')
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[require_platform_admin] = lambda: object()
        monkeypatch.setattr(service.settings, 'CHANNEL_ENCRYPTION_KEY', 'test-key-only')
        yield TestClient(app), db, app
    engine.dispose()


def payload(**changes):
    return dict(enabled=True, client_id='test-client', api_key='private-api', checksum_key='private-checksum',
                return_url='https://example.test/return', cancel_url='https://example.test/cancel',
                account_number='123456', bank_bin='970422', account_name='TEST ACCOUNT', **changes)


def test_save_encrypted_redacted_and_blank_retains(setup):
    client, db, _ = setup
    response = client.put('/api/platform/payment-settings', json=payload())
    assert response.status_code == 200, response.text
    assert 'private-api' not in response.text and 'private-checksum' not in response.text
    assert response.json()['api_key_configured']
    encrypted = db.get(AppSetting, service.PREFIX+'api_key_encrypted').value
    assert encrypted != 'private-api'
    body = payload(); body.update(api_key='', checksum_key='')
    assert client.put('/api/platform/payment-settings', json=body).status_code == 200
    assert db.get(AppSetting, service.PREFIX+'api_key_encrypted').value == encrypted
    assert service.resolve(db, require_enabled=True).PAYOS_API_KEY == 'private-api'


@pytest.mark.parametrize('field,value', [('return_url','http://localhost'),('bank_bin','x'),('account_number','abc'),('api_key','x'*201)])
def test_invalid_settings_never_echo_secrets(setup, field, value):
    client, _, _ = setup
    body=payload(); body[field]=value
    response=client.put('/api/platform/payment-settings',json=body)
    assert response.status_code==422
    assert 'private-api' not in response.text and 'private-checksum' not in response.text
    assert 'input' not in response.text


def test_disabled_blocks_new_checkout_but_keeps_webhook_credentials(setup):
    client, db, _=setup
    assert client.put('/api/platform/payment-settings',json=payload()).status_code==200
    body=payload(); body.update(enabled=False,api_key='',checksum_key='')
    assert client.put('/api/platform/payment-settings',json=body).status_code==200
    with pytest.raises(HTTPException): service.resolve(db,require_enabled=True)
    assert service.resolve(db).PAYOS_CHECKSUM_KEY=='private-checksum'


def test_check_is_configuration_only_and_never_creates_payment(setup, monkeypatch):
    client, _, _=setup
    client.put('/api/platform/payment-settings',json=payload())
    mock=Mock()
    monkeypatch.setattr('app.services.subscription_payment_service.get_client',mock)
    response=client.post('/api/platform/payment-settings/test')
    assert response.status_code==200 and response.json()['status']=='configured'
    mock.return_value.payment_requests.create.assert_not_called()


def test_admin_permission_required(setup):
    client, _, app=setup
    def denied(): raise HTTPException(403,'Forbidden')
    app.dependency_overrides[require_platform_admin]=denied
    for method,path in [('get',''),('put',''),('post','/test')]:
        assert getattr(client,method)('/api/platform/payment-settings'+path,**({'json':payload()} if method=='put' else {})).status_code==403


@pytest.mark.parametrize('status', ['pending', 'expired', 'paid'])
def test_existing_orders_preserve_provider_identity(setup, status):
    client, db, _ = setup
    assert client.put('/api/platform/payment-settings', json=payload()).status_code == 200
    db.add(SubscriptionPaymentAttempt(subscription_id=999, order_code=999, amount=400000,
                                      expires_at=datetime.now(), status=status))
    db.commit()
    assert client.put('/api/platform/payment-settings', json=payload()).status_code == 200
    body = payload(); body['checksum_key'] = 'different-key'
    assert client.put('/api/platform/payment-settings', json=body).status_code == 422
    assert service.resolve(db).PAYOS_CHECKSUM_KEY == 'private-checksum'


def test_first_save_cannot_replace_environment_keys_for_existing_orders(setup, monkeypatch):
    client, db, _ = setup
    monkeypatch.setattr(service.settings, 'PAYOS_CHECKSUM_KEY', 'legacy-key')
    db.add(SubscriptionPaymentAttempt(subscription_id=999, order_code=999, amount=400000,
                                      expires_at=datetime.now(), status='expired'))
    db.commit()
    assert client.put('/api/platform/payment-settings', json=payload()).status_code == 422
