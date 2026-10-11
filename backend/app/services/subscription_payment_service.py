"""Durable payOS checkout and verified receipt recording; never grants access."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import secrets
from urllib.parse import urlparse

from fastapi import HTTPException
from payos import NotFoundError, PayOS
from payos.types import CreatePaymentLinkRequest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.business import Payment, Subscription
from app.models.subscription_payment_attempt import SubscriptionPaymentAttempt as Attempt
from app.schemas.subscription_payment import SubscriptionPaymentOut


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_client(config=None):
    config = config or settings
    required = ("PAYOS_CLIENT_ID", "PAYOS_API_KEY", "PAYOS_CHECKSUM_KEY",
                "PAYOS_RETURN_URL", "PAYOS_CANCEL_URL",
                "PAYOS_EXPECTED_ACCOUNT_NUMBER", "PAYOS_EXPECTED_BANK_BIN")
    missing = [key for key in required if not getattr(config, key).strip()]
    if missing:
        raise HTTPException(503, detail={"code": "payment_not_configured", "missing": missing})
    for key in ("PAYOS_RETURN_URL", "PAYOS_CANCEL_URL"):
        url = urlparse(getattr(config, key))
        if url.scheme != "https" or not url.netloc or url.username or url.password:
            raise HTTPException(503, detail=f"Configure {key} with an HTTPS URL")
    if config.PAYOS_PAYMENT_TTL_SECONDS <= 0:
        raise HTTPException(503, detail="PAYOS_PAYMENT_TTL_SECONDS must be positive")
    return PayOS(client_id=config.PAYOS_CLIENT_ID, api_key=config.PAYOS_API_KEY,
                 checksum_key=config.PAYOS_CHECKSUM_KEY, timeout=10, max_retries=0)


def lock_subscription(db, subscription_id):
    sub = db.scalar(select(Subscription).where(Subscription.id == subscription_id)
                    .with_for_update().execution_options(populate_existing=True))
    if sub is None:
        raise HTTPException(404, "Subscription not found")
    return sub


def get_attempt(db, subscription_id):
    return db.scalar(select(Attempt).where(Attempt.subscription_id == subscription_id)
                     .with_for_update().execution_options(populate_existing=True))


def paid_receipt(db, sub):
    return db.scalar(select(Payment).where(Payment.subscription_id == sub.id,
                                          Payment.status == "paid", Payment.currency == "VND",
                                          Payment.amount > 0))


def quoted_amount(sub):
    from app.api.onboarding import _chatbot_rental_price
    quote = getattr(sub, "quoted_amount", None)
    if quote is None:
        quote = _chatbot_rental_price(sub.plan) if sub.service_type == "chatbot" else sub.plan.price
    amount = Decimal(str(quote))
    if (not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value()
            or amount > 9999999999 or getattr(sub, "quoted_currency", "VND") != "VND"):
        raise HTTPException(422, "Payment requires a positive integer VND quote within ledger limits")
    return int(amount)


def snapshot_link(attempt, link, config=None):
    config = config or settings
    if (link.order_code != attempt.order_code or link.amount != attempt.amount
            or link.currency != attempt.currency or not link.payment_link_id
            or not link.account_number or not link.bin
            or (attempt.payment_link_id and attempt.payment_link_id != link.payment_link_id)):
        raise HTTPException(502, "payOS response does not match the frozen payment order")
    if ((config.PAYOS_EXPECTED_ACCOUNT_NUMBER and link.account_number != config.PAYOS_EXPECTED_ACCOUNT_NUMBER)
            or (config.PAYOS_EXPECTED_BANK_BIN and link.bin != config.PAYOS_EXPECTED_BANK_BIN)):
        raise HTTPException(502, "payOS recipient does not match configured bank account")
    checkout = urlparse(link.checkout_url)
    if (not link.qr_code or checkout.scheme != "https" or checkout.hostname != "pay.payos.vn"
            or checkout.username or checkout.password or checkout.port not in {None, 443}):
        raise HTTPException(502, "payOS response is missing secure checkout details")
    attempt.payment_link_id = link.payment_link_id
    attempt.qr_code = link.qr_code
    attempt.checkout_url = link.checkout_url
    attempt.bank_bin = link.bin
    attempt.account_name = link.account_name
    attempt.account_number = link.account_number
    attempt.status = "pending" if getattr(link, "status", "PENDING") == "PENDING" else "reconciliation_required"
    attempt.reconciliation_required = attempt.status == "reconciliation_required"


def create_payment(db, sub):
    sub = lock_subscription(db, sub.id)
    if getattr(sub, "change_kind", "new") == "downgrade":
        raise HTTPException(409, "Downgrade requests do not require payment")
    if sub.status not in {"pending", "active"}:
        raise HTTPException(409, "Subscription request is no longer payable")
    attempt = get_attempt(db, sub.id)
    if payment_status(db, sub, attempt).status == "refunded":
        return attempt
    if paid_receipt(db, sub):
        return attempt
    if attempt and attempt.status == "paid":
        return attempt
    from app.services.platform_payment_settings import resolve, lock_configuration
    lock_configuration(db)
    config = resolve(db, require_enabled=True)
    client = get_client(config)
    fresh = attempt is None
    if fresh:
        attempt = Attempt(subscription_id=sub.id, order_code=secrets.randbelow(2**53 - 1) + 1,
                          amount=quoted_amount(sub), currency="VND", status="creating", reference=f"SUB {sub.id}",
                          account_number=config.PAYOS_EXPECTED_ACCOUNT_NUMBER,
                          bank_bin=config.PAYOS_EXPECTED_BANK_BIN,
                          expires_at=now() + timedelta(seconds=config.PAYOS_PAYMENT_TTL_SECONDS))
        db.add(attempt)
        try:
            # Commit the identity before the first provider call.
            db.commit()
        except IntegrityError:
            db.rollback()
            sub = lock_subscription(db, sub.id)
            attempt = get_attempt(db, sub.id)
            if attempt is None:
                raise HTTPException(409, "Order identity collision; retry checkout")
            fresh = False
    sub = lock_subscription(db, sub.id)
    attempt = get_attempt(db, sub.id)
    if paid_receipt(db, sub) or attempt.status == "paid":
        return attempt
    if sub.status not in {"pending", "active"}:
        raise HTTPException(409, "Subscription request is no longer payable")
    if attempt.qr_code or attempt.status != "creating":
        return attempt
    if attempt.expires_at <= now():
        attempt.status = "expired"
        db.commit()
        return attempt
    try:
        if not fresh:
            try:
                recovered = client.payment_requests.get(attempt.order_code)
            except NotFoundError:
                recovered = None
            if recovered is not None:
                if (recovered.order_code != attempt.order_code or recovered.amount != attempt.amount
                        or not recovered.id
                        or (attempt.payment_link_id and recovered.id != attempt.payment_link_id)):
                    raise HTTPException(502, "Recovered payOS order does not match")
                attempt.payment_link_id = recovered.id
                attempt.account_number = attempt.account_number or config.PAYOS_EXPECTED_ACCOUNT_NUMBER
                attempt.bank_bin = attempt.bank_bin or config.PAYOS_EXPECTED_BANK_BIN
                # shortcut: lookup omits QR/recipient, validate configured recipient and reconcile manually.
                attempt.status = "reconciliation_required"
                attempt.reconciliation_required = True
                db.commit()
                return attempt
        link = client.payment_requests.create(CreatePaymentLinkRequest(
            order_code=attempt.order_code, amount=attempt.amount,
            description=attempt.reference, return_url=config.PAYOS_RETURN_URL,
            cancel_url=config.PAYOS_CANCEL_URL,
            expired_at=int(attempt.expires_at.replace(tzinfo=timezone.utc).timestamp()),
        ))
        snapshot_link(attempt, link, config)
        db.commit()
        return attempt
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(503, detail={"code": "payment_provider_unavailable",
                                       "message": "Retry this same subscription payment; its order is saved"}) from exc


def payment_status(db, sub, attempt=None):
    attempt = attempt or db.scalar(select(Attempt).where(Attempt.subscription_id == sub.id))
    receipt = paid_receipt(db, sub)
    refunded = None if receipt else db.scalar(select(Payment).where(
        Payment.subscription_id == sub.id, Payment.status == "refunded",
        Payment.currency == "VND", Payment.amount > 0,
    ).order_by(Payment.id.desc()))
    if attempt is None:
        terminal_receipt = receipt or refunded
        return SubscriptionPaymentOut(status="paid" if receipt else "refunded" if refunded else "not_created",
            amount=int(terminal_receipt.amount) if terminal_receipt else None, approval_status=sub.status,
            reconciliation_required=bool(receipt and sub.status not in {"pending", "active"}))
    status = "paid" if receipt else "refunded" if refunded else attempt.status
    if status == "pending" and attempt.expires_at <= now():
        status = "expired"
    if status not in {"paid", "refunded"} and sub.status not in {"pending", "active"}:
        status = "cancelled"
    show_checkout = status == "pending"
    return SubscriptionPaymentOut(status=status, amount=attempt.amount, currency=attempt.currency,
        provider='vietqr' if (attempt.payment_link_id or '').startswith('vietqr:') else 'payos',
        qr_code=attempt.qr_code if show_checkout else None,
        checkout_url=attempt.checkout_url if show_checkout else None,
        bank_name=attempt.bank_name, bin=attempt.bank_bin, account_name=attempt.account_name,
        account_number=attempt.account_number, reference=attempt.reference,
        expires_at=attempt.expires_at, approval_status=sub.status,
        reconciliation_required=attempt.reconciliation_required or bool(receipt and sub.status not in {"pending", "active"}))


def receive_webhook(db, payload):
    from app.services.platform_payment_settings import resolve
    config = resolve(db)
    client = get_client(config)
    try:
        data = client.webhooks.verify(payload)
    except Exception as exc:
        raise HTTPException(400, "Invalid payOS webhook signature or schema") from exc
    if data.code != "00" or payload.get("success") is not True or payload.get("code") != "00":
        raise HTTPException(400, "Webhook is not a successful payment")
    identity = db.scalar(select(Attempt).where(Attempt.order_code == data.order_code))
    if identity is None:
        # Acknowledge only the signed registration sample, never book its fictitious transfer.
        if data.desc in {"Thanh cong", "Thành công"} and data.model_dump(exclude={"desc"}) == {
            "order_code": 123, "amount": 3000, "description": "VQRIO123",
            "account_number": "12345678", "reference": "TF230204212323",
            "transaction_date_time": "2023-02-04 18:25:00", "currency": "VND",
            "payment_link_id": "124c33293c43417ab7879e14c8d9eb18", "code": "00",
            "counter_account_bank_id": "", "counter_account_bank_name": "",
            "counter_account_name": "", "counter_account_number": "",
            "virtual_account_name": "", "virtual_account_number": "",
        }:
            return {"accepted": True}
        raise HTTPException(404, "Unknown payment order")
    sub = lock_subscription(db, identity.subscription_id)
    attempt = get_attempt(db, sub.id)
    if (data.amount != attempt.amount or data.currency != attempt.currency
            or data.payment_link_id != attempt.payment_link_id
            or not attempt.account_number or data.account_number != attempt.account_number
            or not data.reference
            or (config.PAYOS_EXPECTED_ACCOUNT_NUMBER and data.account_number != config.PAYOS_EXPECTED_ACCOUNT_NUMBER)
            or (config.PAYOS_EXPECTED_BANK_BIN and attempt.bank_bin != config.PAYOS_EXPECTED_BANK_BIN)):
        raise HTTPException(409, "Payment identity, amount, currency or recipient mismatch")
    transaction_id = f"payos:{data.reference}"
    if len(transaction_id) > 255:
        raise HTTPException(422, "Payment reference is too long")
    existing = db.scalar(select(Payment).where(Payment.provider_transaction_id == transaction_id))
    manual_receipt = db.scalar(select(Payment).where(
        Payment.subscription_id == sub.id, Payment.business_id == sub.business_id,
        Payment.status == "paid", Payment.provider != "payos", Payment.currency == "VND",
        Payment.amount > 0,
    ).order_by(Payment.provider_transaction_id.in_([data.reference, transaction_id]).desc(), Payment.id)
        .with_for_update().execution_options(populate_existing=True))
    if existing is not None:
        if (existing.subscription_id != sub.id or existing.business_id != sub.business_id
                or existing.status not in ({"paid", "refunded"} if existing.provider == "payos" else {"paid"})
                or existing.currency != "VND" or existing.amount <= 0
                or (existing.provider == "payos" and
                    (existing.amount != attempt.amount or existing.currency != attempt.currency))):
            raise HTTPException(409, "Transaction reference already belongs to a different receipt")
        if existing.provider == "payos":
            return {"accepted": True}
        manual_receipt = existing
    attempt.reconciliation_required = bool(attempt.reconciliation_required or paid_receipt(db, sub) or sub.status not in {"pending", "active"}
                                           or attempt.expires_at <= now())
    attempt.status = "paid"
    attempt.provider_transaction_reference = data.reference
    if manual_receipt is not None:
        # Manual reference formats cannot prove a separate transfer; retain evidence without booking twice.
        metadata = dict(manual_receipt.raw_response or {})
        observations = list(metadata.get("payos_verified_payments_pending_review", []))
        if not any(row["reference"] == data.reference and row["order_code"] == attempt.order_code for row in observations):
            observations.append({"order_code": attempt.order_code, "payment_link_id": attempt.payment_link_id,
                "reference": data.reference, "amount": attempt.amount, "currency": attempt.currency,
                "account_number": attempt.account_number, "bank_bin": attempt.bank_bin,
                "verified_at": now().isoformat(), "reconciliation_required": True})
        metadata["payos_verified_payments_pending_review"] = observations
        manual_receipt.raw_response = metadata
    else:
        db.add(Payment(business_id=sub.business_id, subscription_id=sub.id, amount=attempt.amount,
                       currency=attempt.currency, provider="payos", provider_transaction_id=transaction_id,
                       status="paid", paid_at=now(), raw_response={"order_code": attempt.order_code,
                       "payment_link_id": attempt.payment_link_id, "reference": data.reference,
                       "reconciliation_required": attempt.reconciliation_required}))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Concurrent receipt conflict; retry webhook") from exc
    return {"accepted": True}
