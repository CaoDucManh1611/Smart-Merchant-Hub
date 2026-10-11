from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business, Payment, ServicePlan, Subscription
from app.models.subscription_payment_attempt import SubscriptionPaymentAttempt
from app.models.setting import AppSetting
from app.services import vietqr_payment_service as service
from app.services.subscription_payment_service import payment_status, now


@pytest.fixture
def setup():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Business.metadata.create_all(engine)
    with Session(engine) as db:
        shop = Business(name='VietQR Test', slug='vietqr-test')
        plan = ServicePlan(code='vietqr-test', name='Test', price=Decimal('400000'))
        db.add_all([shop, plan]); db.flush()
        sub = Subscription(business_id=shop.id, plan_id=plan.id, status='pending',
                           quoted_amount=400000, quoted_currency='VND', change_kind='upgrade')
        db.add(sub); db.commit()
        service.save(db, service.PaymentSettingsUpdate(enabled=True, bank_bin='970422',
                     account_number='00123456789', account_name='TEST RECIPIENT'))
        db.commit()
        yield db, sub
    engine.dispose()


def test_known_vietqr_reference_vector():
    assert service.qr_content('963388', '3456789143', 2345123, 'thanh toan hoa don') == (
        '00020101021138540010A00000072701240006963388011034567891430208QRIBFTTA'
        '5303704540723451235802VN62220818thanh toan hoa don630445F2')


def test_legacy_request_freezes_quote_for_admin_receipt(setup):
    db, sub = setup
    sub.quoted_amount = None
    db.commit()
    attempt = service.create_payment(db, sub)
    sub.plan.price = 999999
    db.commit()
    assert sub.quoted_amount == attempt.amount == 400000


def test_local_qr_frozen_idempotent_without_payment_or_activation(setup, monkeypatch):
    db, sub = setup
    sdk = Mock(side_effect=AssertionError('No external provider calls'))
    monkeypatch.setattr('app.services.subscription_payment_service.get_client', sdk)
    first = service.create_payment(db, sub)
    assert first.reference == f'SMH{sub.id}' and first.account_number == '00123456789'
    assert first.amount == 400000 and first.qr_code.startswith('000201')
    sub.plan.price = 999999; db.commit()
    service.save(db, service.PaymentSettingsUpdate(enabled=True, bank_bin='970407',
                 account_number='998877', account_name='NEW RECIPIENT')); db.commit()
    again = service.create_payment(db, sub)
    assert again.id == first.id and again.amount == 400000 and again.bank_bin == '970422'
    assert payment_status(db, sub).status == 'pending'
    assert payment_status(db, sub).provider == 'vietqr'
    assert sub.status == 'pending' and db.scalar(select(Payment.id)) is None
    sdk.assert_not_called()


def test_manual_receipt_updates_shop_status_without_activating_plan(setup):
    db, sub = setup
    service.create_payment(db, sub)
    db.add(Payment(business_id=sub.business_id, subscription_id=sub.id, amount=400000,
                   currency='VND', provider='manual', provider_transaction_id='BANK-TEST', status='paid'))
    db.commit()
    result = payment_status(db, sub)
    assert result.status == 'paid' and result.qr_code is None and result.approval_status == 'pending'


def test_downgrade_never_creates_payment_or_refund(setup):
    db, sub = setup
    sub.change_kind = 'downgrade'; db.commit()
    with pytest.raises(HTTPException) as error: service.create_payment(db, sub)
    assert error.value.status_code == 409
    assert db.scalar(select(SubscriptionPaymentAttempt.id)) is None
    assert db.scalar(select(Payment.id)) is None


def test_expired_qr_is_hidden_and_not_regenerated(setup):
    db, sub = setup
    attempt = service.create_payment(db, sub)
    attempt.expires_at = now() - timedelta(seconds=1); db.commit()
    assert service.create_payment(db, sub).id == attempt.id
    assert payment_status(db, sub).status == 'expired' and payment_status(db, sub).qr_code is None


def test_configuration_disabled_fails_closed_for_new_qr(setup):
    db, sub = setup
    service.save(db, service.PaymentSettingsUpdate(enabled=False)); db.commit()
    with pytest.raises(HTTPException) as error: service.create_payment(db, sub)
    assert error.value.status_code == 503 and db.scalar(select(SubscriptionPaymentAttempt.id)) is None


@pytest.mark.parametrize('field,value', [('bank_bin','123456'), ('account_number','abc'),
    ('account_number','1'*35), ('account_name','\x00BAD')])
def test_invalid_bank_settings_rejected(field, value):
    body = dict(enabled=True, bank_bin='970422', account_number='123456', account_name='TEST')
    body[field] = value
    with pytest.raises(ValueError): service.PaymentSettingsUpdate(**body)


def test_old_payos_attempt_is_preserved_and_no_new_order_created(setup):
    db, sub = setup
    old = SubscriptionPaymentAttempt(subscription_id=sub.id, order_code=111, amount=400000,
          status='pending', payment_link_id='legacy-payos-link', qr_code='legacy-qr',
          account_number='123456', bank_bin='970422', expires_at=now()+timedelta(hours=1))
    db.add(old); db.commit()
    assert service.create_payment(db, sub).id == old.id
    assert payment_status(db, sub).provider == 'payos'
