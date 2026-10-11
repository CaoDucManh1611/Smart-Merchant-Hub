from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from payos import NotFoundError, PayOS
from payos.types import WebhookData

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.business import Business, Payment, ServicePlan, Subscription
from app.models.subscription_payment_attempt import SubscriptionPaymentAttempt
from app.services import subscription_payment_service as service


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'payments.db'}")
    Business.metadata.create_all(engine)
    db = Session(engine)
    business = Business(name="Test", slug="payment-test")
    plan = ServicePlan(code="payment-test", name="Test", price=Decimal(120000))
    db.add_all([business, plan])
    db.flush()
    sub = Subscription(business_id=business.id, plan_id=plan.id, status="pending")
    db.add(sub)
    db.commit()
    sdk = Mock()
    sdk.payment_requests.create.side_effect = lambda request: SimpleNamespace(
        order_code=request.order_code, amount=request.amount, currency="VND",
        payment_link_id="link-1", qr_code="signed-qr", checkout_url="https://pay.payos.vn/test",
        bin="970422", account_name="MERCHANT", account_number="123456",
    )
    monkeypatch.setattr(service, "get_client", lambda config=None: sdk)
    monkeypatch.setattr(service.settings, "PAYOS_RETURN_URL", "https://example.test/return")
    monkeypatch.setattr(service.settings, "PAYOS_CANCEL_URL", "https://example.test/cancel")
    monkeypatch.setattr(service.settings, "PAYOS_EXPECTED_ACCOUNT_NUMBER", "123456")
    monkeypatch.setattr(service.settings, "PAYOS_EXPECTED_BANK_BIN", "970422")
    yield db, sub, sdk
    db.close()
    engine.dispose()


def callback(sdk, attempt, **changes):
    data = dict(order_code=attempt.order_code, amount=attempt.amount, currency="VND",
                payment_link_id="link-1", account_number="123456", reference="bank-ref", code="00")
    data.update(changes)
    sdk.webhooks.verify.return_value = SimpleNamespace(**data)
    return {"success": True, "code": "00", "data": {}, "signature": "mock"}


def test_create_is_durable_idempotent_and_frozen(setup):
    db, sub, sdk = setup
    first = service.create_payment(db, sub)
    sub.plan.price = Decimal(999999)
    db.commit()
    second = service.create_payment(db, sub)
    assert first.id == second.id and second.amount == 120000
    assert sdk.payment_requests.create.call_count == 1
    assert sub.status == "pending"


def test_timeout_retries_same_persisted_order(setup):
    db, sub, sdk = setup
    create = sdk.payment_requests.create.side_effect
    sdk.payment_requests.create.side_effect = TimeoutError()
    with pytest.raises(HTTPException) as error:
        service.create_payment(db, sub)
    assert error.value.status_code == 503
    attempt = db.scalar(select(SubscriptionPaymentAttempt))
    order = attempt.order_code
    sdk.payment_requests.get.side_effect = NotFoundError("not found")
    sdk.payment_requests.create.side_effect = create
    assert service.create_payment(db, sub).order_code == order


@pytest.mark.parametrize("changes", [{"amount": 1}, {"currency": "USD"},
    {"payment_link_id": "other"}, {"account_number": "other"}, {"code": "01"}])
def test_callback_rejects_mismatch(setup, changes):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    with pytest.raises(HTTPException):
        service.receive_webhook(db, callback(sdk, attempt, **changes))
    assert db.scalar(select(Payment)) is None


def test_replay_records_one_receipt_without_activation(setup):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    payload = callback(sdk, attempt)
    service.receive_webhook(db, payload)
    service.receive_webhook(db, payload)
    assert len(db.scalars(select(Payment)).all()) == 1
    assert sub.status == "pending"
    assert attempt.status == "paid"


def test_late_cancelled_payment_requires_reconciliation(setup):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    sub.status = "cancelled"
    db.commit()
    service.receive_webhook(db, callback(sdk, attempt))
    assert attempt.reconciliation_required
    assert db.scalar(select(Payment)).status == "paid"
    assert sub.status == "cancelled"


def test_invalid_signature_never_records_payment(setup):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    payload = callback(sdk, attempt)
    sdk.webhooks.verify.side_effect = ValueError("invalid signature")
    with pytest.raises(HTTPException) as error:
        service.receive_webhook(db, payload)
    assert error.value.status_code == 400
    assert db.scalar(select(Payment)) is None


def test_downgrade_never_creates_attempt(setup):
    db, sub, sdk = setup
    sub.change_kind = "downgrade"
    with pytest.raises(HTTPException):
        service.create_payment(db, sub)
    assert db.scalar(select(SubscriptionPaymentAttempt)) is None


def test_manual_paid_receipt_is_visible_without_provider_call(setup):
    db, sub, sdk = setup
    db.add(Payment(business_id=sub.business_id, subscription_id=sub.id, amount=120000,
                   currency="VND", provider="manual", status="paid", provider_transaction_id="manual-1"))
    db.commit()
    assert service.create_payment(db, sub) is None
    status = service.payment_status(db, sub)
    assert status.status == "paid" and status.amount == 120000
    sdk.payment_requests.create.assert_not_called()


def test_frozen_quote_overrides_catalog(setup):
    db, sub, sdk = setup
    sub.quoted_amount = Decimal(80000)
    db.commit()
    assert service.create_payment(db, sub).amount == 80000


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("1.5"), Decimal("-1")])
def test_invalid_quote_never_calls_provider(setup, value):
    db, sub, sdk = setup
    sub.quoted_amount = value
    db.commit()
    with pytest.raises(HTTPException):
        service.create_payment(db, sub)
    sdk.payment_requests.create.assert_not_called()


def test_lost_create_response_recovers_without_claiming_paid(setup):
    db, sub, sdk = setup
    sdk.payment_requests.create.side_effect = TimeoutError()
    with pytest.raises(HTTPException):
        service.create_payment(db, sub)
    attempt = db.scalar(select(SubscriptionPaymentAttempt))
    sdk.payment_requests.get.return_value = SimpleNamespace(
        order_code=attempt.order_code, amount=attempt.amount, id="link-1", status="PAID")
    recovered = service.create_payment(db, sub)
    assert recovered.status == "reconciliation_required" and recovered.reconciliation_required
    assert service.payment_status(db, sub).qr_code is None
    assert db.scalar(select(Payment)) is None


def test_lookup_outage_never_creates_another_order(setup):
    db, sub, sdk = setup
    sdk.payment_requests.create.side_effect = TimeoutError()
    with pytest.raises(HTTPException):
        service.create_payment(db, sub)
    sdk.payment_requests.get.side_effect = TimeoutError()
    with pytest.raises(HTTPException):
        service.create_payment(db, sub)
    assert sdk.payment_requests.create.call_count == 1


def test_recipient_config_mismatch_blocks_checkout(setup, monkeypatch):
    db, sub, sdk = setup
    monkeypatch.setattr(service.settings, "PAYOS_EXPECTED_ACCOUNT_NUMBER", "different")
    with pytest.raises(HTTPException) as error:
        service.create_payment(db, sub)
    assert error.value.status_code == 502
    assert service.payment_status(db, sub).qr_code is None


def test_missing_config_returns_actionable_503(monkeypatch):
    monkeypatch.setattr(service.settings, "PAYOS_CLIENT_ID", "")
    with pytest.raises(HTTPException) as error:
        service.get_client()
    assert error.value.status_code == 503
    assert "PAYOS_CLIENT_ID" in error.value.detail["missing"]


@pytest.mark.parametrize("missing", ["PAYOS_CLIENT_ID", "PAYOS_API_KEY", "PAYOS_CHECKSUM_KEY",
    "PAYOS_RETURN_URL", "PAYOS_CANCEL_URL", "PAYOS_EXPECTED_ACCOUNT_NUMBER", "PAYOS_EXPECTED_BANK_BIN"])
def test_each_required_config_fails_closed(monkeypatch, missing):
    required = ["PAYOS_CLIENT_ID", "PAYOS_API_KEY", "PAYOS_CHECKSUM_KEY", "PAYOS_RETURN_URL",
                "PAYOS_CANCEL_URL", "PAYOS_EXPECTED_ACCOUNT_NUMBER", "PAYOS_EXPECTED_BANK_BIN"]
    for key in required:
        monkeypatch.setattr(service.settings, key, "https://example.test" if key.endswith("URL") else "mock")
    monkeypatch.setattr(service.settings, missing, "")
    with pytest.raises(HTTPException) as error:
        service.get_client()
    assert error.value.status_code == 503 and error.value.detail["missing"] == [missing]


def test_expired_checkout_hides_qr_and_late_callback_accounts_money(setup):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    attempt.expires_at = service.now() - service.timedelta(seconds=1)
    db.commit()
    status = service.payment_status(db, sub)
    assert status.status == "expired" and status.qr_code is None
    service.receive_webhook(db, callback(sdk, attempt))
    assert attempt.reconciliation_required and db.scalar(select(Payment)).status == "paid"


def test_concurrent_database_attempt_uniqueness(setup):
    db, sub, sdk = setup
    engine, subscription_id = db.bind, sub.id
    barrier = Barrier(2)
    def insert(order):
        with Session(engine) as worker:
            worker.add(SubscriptionPaymentAttempt(subscription_id=subscription_id, order_code=order,
                amount=120000, expires_at=service.now(), status="creating"))
            barrier.wait(timeout=5)
            try:
                worker.commit()
                return "created"
            except IntegrityError:
                worker.rollback()
                return "duplicate"
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(insert, [1001, 1002])) == ["created", "duplicate"]
    assert len(db.scalars(select(SubscriptionPaymentAttempt)).all()) == 1


def test_concurrent_callback_replay_records_once(setup):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    payload = callback(sdk, attempt)
    engine = db.bind
    def receive(_):
        with Session(engine) as worker:
            try:
                return service.receive_webhook(worker, payload)
            except HTTPException as error:
                assert error.status_code == 409
                worker.rollback()
                return service.receive_webhook(worker, payload)
    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(receive, [1, 2])) == [{"accepted": True}, {"accepted": True}]
    assert len(db.scalars(select(Payment)).all()) == 1


def test_routes_scope_auth_and_manual_receipt(setup):
    from app.services import vietqr_payment_service as vietqr
    from app.api.subscription_payments import router
    from app.auth.dependencies import get_current_user
    from app.db.dependencies import get_db
    db, sub, sdk = setup
    vietqr.save(db, vietqr.PaymentSettingsUpdate(enabled=True, bank_bin="970422",
                account_number="123456", account_name="TEST MERCHANT"))
    db.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    actor = SimpleNamespace(business_id=sub.business_id, role="owner")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    with TestClient(app) as client:
        path = f"/api/onboarding/shops/{sub.business_id}/subscription/{sub.id}/payment"
        assert client.get(path).json()["status"] == "not_created"
        result = client.post(path).json()
        assert result["provider"] == "vietqr" and result["qr_code"].startswith("000201")
        assert client.get(path).json()["approval_status"] == "pending"
        actor.business_id = sub.business_id + 1
        assert client.get(path).status_code == 404
        assert client.post(path).status_code == 404
        app.dependency_overrides.pop(get_current_user)
        assert client.get(path).status_code == 401


def test_transfer_reference_is_immutable_and_extra_payment_is_accounted(setup):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    reference = f"SUB {sub.id}"
    assert attempt.reference == sdk.payment_requests.create.call_args.args[0].description == reference
    service.receive_webhook(db, callback(sdk, attempt))
    assert attempt.reference == reference and attempt.provider_transaction_reference == "bank-ref"
    service.receive_webhook(db, callback(sdk, attempt, reference="second-bank-ref"))
    service.receive_webhook(db, callback(sdk, attempt, reference="second-bank-ref"))
    assert len(db.scalars(select(Payment)).all()) == 2
    assert attempt.reference == reference and attempt.reconciliation_required


def test_foreign_checkout_host_is_rejected(setup):
    db, sub, sdk = setup
    create = sdk.payment_requests.create.side_effect
    def foreign(request):
        link = create(request)
        link.checkout_url = "https://pay.payos.vn.attacker.test/checkout"
        return link
    sdk.payment_requests.create.side_effect = foreign
    with pytest.raises(HTTPException) as error:
        service.create_payment(db, sub)
    assert error.value.status_code == 502


@pytest.mark.parametrize("manual_reference", ["bank-ref", "payos:bank-ref", "unclear-manual-ref"])
def test_manual_receipt_and_webhook_do_not_double_revenue(setup, manual_reference):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    receipt = Payment(business_id=sub.business_id, subscription_id=sub.id, amount=120000,
        currency="VND", provider="manual", status="paid", provider_transaction_id=manual_reference,
        raw_response={"admin_note": "preserve"})
    db.add(receipt)
    db.commit()
    payload = callback(sdk, attempt)
    assert service.receive_webhook(db, payload) == {"accepted": True}
    service.receive_webhook(db, payload)
    rows = db.scalars(select(Payment)).all()
    assert rows == [receipt] and sum(row.amount for row in rows) == 120000
    assert receipt.provider == "manual" and receipt.raw_response["admin_note"] == "preserve"
    observations = receipt.raw_response["payos_verified_payments_pending_review"]
    assert len(observations) == 1 and observations[0]["reference"] == "bank-ref"
    assert observations[0]["amount"] == 120000
    assert attempt.status == "paid" and attempt.reconciliation_required
    assert attempt.provider_transaction_reference == "bank-ref"
    assert service.payment_status(db, sub).status == "paid"
    assert sub.status == "pending"


def test_unclear_manual_overlap_preserves_distinct_verified_transfers_for_review(setup):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    receipt = Payment(business_id=sub.business_id, subscription_id=sub.id, amount=120000,
        currency="VND", provider="manual", status="paid", provider_transaction_id="unrelated-manual")
    db.add(receipt)
    db.commit()
    service.receive_webhook(db, callback(sdk, attempt))
    service.receive_webhook(db, callback(sdk, attempt, reference="distinct-transfer"))
    service.receive_webhook(db, callback(sdk, attempt, reference="bank-ref"))
    assert len(db.scalars(select(Payment)).all()) == 1
    observations = receipt.raw_response["payos_verified_payments_pending_review"]
    assert {row["reference"] for row in observations} == {"bank-ref", "distinct-transfer"}
    assert attempt.reconciliation_required


def test_lost_create_recovery_accepts_verified_callback_with_configured_recipient(setup):
    db, sub, sdk = setup
    sdk.payment_requests.create.side_effect = TimeoutError()
    with pytest.raises(HTTPException):
        service.create_payment(db, sub)
    attempt = db.scalar(select(SubscriptionPaymentAttempt))
    sdk.payment_requests.get.return_value = SimpleNamespace(
        order_code=attempt.order_code, amount=attempt.amount, id="link-1", status="PAID")
    recovered = service.create_payment(db, sub)
    assert recovered.account_number == "123456" and recovered.bank_bin == "970422"
    assert service.payment_status(db, sub).qr_code is None
    service.receive_webhook(db, callback(sdk, attempt))
    assert db.scalar(select(Payment)).amount == 120000
    assert service.payment_status(db, sub).status == "paid"
    assert attempt.reconciliation_required and sub.status == "pending"


@pytest.mark.parametrize("amount,currency", [(0, "VND"), (120000, "USD")])
def test_legacy_zero_or_foreign_receipt_does_not_block_checkout(setup, amount, currency):
    db, sub, sdk = setup
    db.add(Payment(business_id=sub.business_id, subscription_id=sub.id, amount=amount,
        currency=currency, provider="manual", status="paid", provider_transaction_id="legacy-receipt"))
    db.commit()
    assert service.paid_receipt(db, sub) is None
    assert service.payment_status(db, sub).status == "not_created"
    attempt = service.create_payment(db, sub)
    assert attempt is not None and service.payment_status(db, sub).status == "pending"
    sdk.payment_requests.create.assert_called_once()


@pytest.mark.parametrize("amount,currency", [(0, "VND"), (120000, "USD")])
def test_legacy_zero_or_foreign_receipt_does_not_suppress_verified_vnd_receipt(setup, amount, currency):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    legacy = Payment(business_id=sub.business_id, subscription_id=sub.id, amount=amount,
        currency=currency, provider="manual", status="paid", provider_transaction_id="legacy-receipt")
    db.add(legacy)
    db.commit()
    service.receive_webhook(db, callback(sdk, attempt))
    service.receive_webhook(db, callback(sdk, attempt))
    receipt = service.paid_receipt(db, sub)
    assert receipt is not legacy and receipt.provider == "payos"
    assert receipt.amount == 120000 and receipt.currency == "VND"
    assert len(db.scalars(select(Payment)).all()) == 2
    assert legacy.raw_response is None
    assert service.payment_status(db, sub).status == "paid"
    assert not attempt.reconciliation_required


@pytest.mark.parametrize("subscription_status", ["pending", "cancelled"])
def test_refunded_ledger_overrides_stale_paid_attempt_and_replay_is_read_only(setup, subscription_status):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    payload = callback(sdk, attempt)
    service.receive_webhook(db, payload)
    receipt = db.scalar(select(Payment))
    receipt.status = "refunded"
    sub.status = subscription_status
    db.commit()
    status = service.payment_status(db, sub)
    assert status.status == "refunded" and status.qr_code is None and status.checkout_url is None
    attempt_before = (attempt.status, attempt.provider_transaction_reference, attempt.reconciliation_required)
    receipt_before = (receipt.status, receipt.amount, receipt.raw_response.copy(), receipt.paid_at)
    assert service.receive_webhook(db, payload) == {"accepted": True}
    assert (attempt.status, attempt.provider_transaction_reference, attempt.reconciliation_required) == attempt_before
    assert (receipt.status, receipt.amount, receipt.raw_response, receipt.paid_at) == receipt_before
    assert len(db.scalars(select(Payment)).all()) == 1


def test_refunded_manual_receipt_is_terminal_without_creating_checkout(setup):
    db, sub, sdk = setup
    db.add(Payment(business_id=sub.business_id, subscription_id=sub.id, amount=120000,
        currency="VND", provider="manual", status="refunded", provider_transaction_id="refunded-manual"))
    db.commit()
    assert service.payment_status(db, sub).status == "refunded"
    assert service.create_payment(db, sub) is None
    sdk.payment_requests.create.assert_not_called()


def test_positive_paid_receipt_takes_precedence_over_refunded_receipt(setup):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    service.receive_webhook(db, callback(sdk, attempt))
    first = db.scalar(select(Payment))
    service.receive_webhook(db, callback(sdk, attempt, reference="second-transfer"))
    first.status = "refunded"
    db.commit()
    assert service.payment_status(db, sub).status == "paid"


def test_refunded_replay_still_rejects_mismatched_identity(setup):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    service.receive_webhook(db, callback(sdk, attempt))
    receipt = db.scalar(select(Payment))
    receipt.status = "refunded"
    receipt.amount = 1
    db.commit()
    with pytest.raises(HTTPException) as error:
        service.receive_webhook(db, callback(sdk, attempt))
    assert error.value.status_code == 409
    assert receipt.status == "refunded" and receipt.amount == 1


@pytest.mark.parametrize("amount,currency", [(0, "VND"), (120000, "USD")])
def test_legacy_reference_collision_does_not_establish_paid_status(setup, amount, currency):
    db, sub, sdk = setup
    attempt = service.create_payment(db, sub)
    legacy = Payment(business_id=sub.business_id, subscription_id=sub.id, amount=amount,
        currency=currency, provider="manual", status="paid", provider_transaction_id="payos:bank-ref")
    db.add(legacy)
    db.commit()
    with pytest.raises(HTTPException) as error:
        service.receive_webhook(db, callback(sdk, attempt))
    assert error.value.status_code == 409
    assert service.payment_status(db, sub).status == "pending"
    assert service.paid_receipt(db, sub) is None
    assert len(db.scalars(select(Payment)).all()) == 1
    assert legacy.raw_response is None


REGISTRATION_SAMPLE = {
    "orderCode": 123, "amount": 3000, "description": "VQRIO123",
    "accountNumber": "12345678", "reference": "TF230204212323",
    "transactionDateTime": "2023-02-04 18:25:00", "currency": "VND",
    "paymentLinkId": "124c33293c43417ab7879e14c8d9eb18", "code": "00",
    "desc": "Thanh cong", "counterAccountBankId": "", "counterAccountBankName": "",
    "counterAccountName": "", "counterAccountNumber": "",
    "virtualAccountName": "", "virtualAccountNumber": "",
}


def signed_registration_sample(monkeypatch, **changes):
    client = PayOS(client_id="review", api_key="review", checksum_key="review-only-key")
    data = {**REGISTRATION_SAMPLE, **changes}
    signature = client.crypto.create_signature_from_object(
        dict(WebhookData(**data).model_dump_camel_case()), "review-only-key")
    monkeypatch.setattr(service, "get_client", lambda config=None: client)
    return {"code": "00", "desc": "success", "success": True, "data": data, "signature": signature}


@pytest.mark.parametrize("description", ["Thanh cong", "Thành công"])
def test_signed_registration_probe_is_acknowledged_without_recording_money(monkeypatch, description):
    db = Mock()
    db.scalars.return_value = []
    db.scalar.return_value = None
    payload = signed_registration_sample(monkeypatch, desc=description)
    assert service.receive_webhook(db, payload) == {"accepted": True}
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("orderCode", 124), ("amount", 3001), ("description", "ACTUAL PAYMENT"),
    ("accountNumber", "87654321"), ("reference", "actual-bank-ref"),
    ("transactionDateTime", "2030-01-01 00:00:00"), ("currency", "USD"),
    ("paymentLinkId", "actual-link"), ("counterAccountBankId", "970422"),
    ("counterAccountBankName", "Bank"), ("counterAccountName", "Payer"),
    ("counterAccountNumber", "123"), ("virtualAccountName", "Merchant"),
    ("virtualAccountNumber", "456"), ("desc", "Actual payment"),
])
def test_signed_unknown_actual_payment_is_not_a_registration_probe(monkeypatch, field, value):
    db = Mock()
    db.scalars.return_value = []
    db.scalar.return_value = None
    payload = signed_registration_sample(monkeypatch, **{field: value})
    with pytest.raises(HTTPException) as error:
        service.receive_webhook(db, payload)
    assert error.value.status_code == 404
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_registration_probe_still_requires_valid_signature(monkeypatch):
    db = Mock()
    db.scalars.return_value = []
    payload = signed_registration_sample(monkeypatch)
    payload["signature"] = "invalid"
    with pytest.raises(HTTPException) as error:
        service.receive_webhook(db, payload)
    assert error.value.status_code == 400
    db.scalar.assert_not_called()


@pytest.mark.parametrize("field,value", [("success", False), ("code", "01")])
def test_registration_probe_still_requires_successful_envelope(monkeypatch, field, value):
    db = Mock()
    db.scalars.return_value = []
    payload = signed_registration_sample(monkeypatch)
    payload[field] = value
    with pytest.raises(HTTPException) as error:
        service.receive_webhook(db, payload)
    assert error.value.status_code == 400
    db.scalar.assert_not_called()


def test_registration_probe_never_bypasses_a_matching_local_payment(monkeypatch):
    db = Mock()
    db.scalars.return_value = []
    db.scalar.return_value = SimpleNamespace(subscription_id=17)
    payload = signed_registration_sample(monkeypatch)
    lock = Mock(side_effect=HTTPException(409, "Normal local payment validation"))
    monkeypatch.setattr(service, "lock_subscription", lock)
    with pytest.raises(HTTPException) as error:
        service.receive_webhook(db, payload)
    assert error.value.status_code == 409
    lock.assert_called_once_with(db, 17)
    db.add.assert_not_called()
    db.commit.assert_not_called()
