from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.onboarding import _require_shop_member_for_purchase
from app.auth.dependencies import get_current_user
from app.db.dependencies import get_db
from app.models.audit_log import AuditLog
from app.models.business import Subscription, User
from app.schemas.subscription_payment import SubscriptionPaymentOut
from app.services.audit_service import record_audit
from app.services.subscription_payment_service import get_attempt, paid_receipt, payment_status, receive_webhook
from app.services.vietqr_payment_service import create_payment

router = APIRouter()


def authorized_subscription(db, actor, business_id, subscription_id):
    _require_shop_member_for_purchase(db, business_id, actor)
    sub = db.scalar(select(Subscription).where(Subscription.id == subscription_id,
                                               Subscription.business_id == business_id))
    if sub is None:
        raise HTTPException(404, "Subscription not found for this shop")
    return sub


@router.post("/onboarding/shops/{business_id}/subscription/{subscription_id}/payment", response_model=SubscriptionPaymentOut)
def post_payment(business_id: int, subscription_id: int, db: Session = Depends(get_db),
                 actor: User = Depends(get_current_user)):
    sub = authorized_subscription(db, actor, business_id, subscription_id)
    attempt = create_payment(db, sub)
    return payment_status(db, sub, attempt)


@router.get("/onboarding/shops/{business_id}/subscription/{subscription_id}/payment", response_model=SubscriptionPaymentOut)
def get_payment(business_id: int, subscription_id: int, db: Session = Depends(get_db),
                actor: User = Depends(get_current_user)):
    return payment_status(db, authorized_subscription(db, actor, business_id, subscription_id))


@router.post("/onboarding/shops/{business_id}/subscription/{subscription_id}/payment/confirm")
def confirm_payment(business_id: int, subscription_id: int, db: Session = Depends(get_db),
                    actor: User = Depends(get_current_user)):
    """Move a customer-reported transfer into the admin review queue; never mark it paid."""
    sub = authorized_subscription(db, actor, business_id, subscription_id)
    sub = db.scalar(select(Subscription).where(Subscription.id == sub.id)
                    .with_for_update().execution_options(populate_existing=True))
    if sub.status not in {"awaiting_payment", "pending"}:
        raise HTTPException(409, "Yêu cầu này không còn chờ xác nhận thanh toán.")
    quote = sub.quoted_amount
    if quote is None:
        from app.api.onboarding import _chatbot_rental_price
        quote = _chatbot_rental_price(sub.plan) if sub.service_type == "chatbot" else sub.plan.price
    if quote is None or quote <= 0:
        raise HTTPException(409, "Yêu cầu này không cần thanh toán.")
    if sub.status == "awaiting_payment":
        sub.status = "pending"
    already_reported = db.scalar(select(AuditLog.id).where(
        AuditLog.business_id == business_id,
        AuditLog.action == "subscription_customer_reported_payment",
        AuditLog.resource_type == "subscription",
        AuditLog.resource_id == str(sub.id),
    ).limit(1))
    if already_reported is None:
        record_audit(
            db,
            business_id=business_id,
            user_id=actor.id,
            action="subscription_customer_reported_payment",
            resource_type="subscription",
            resource_id=sub.id,
            metadata={"verified": False, "note": "Customer assertion; admin must verify bank receipt."},
        )
    db.commit()
    return {"id": sub.id, "status": sub.status, "customer_reported_payment": True}


@router.post("/onboarding/shops/{business_id}/subscription/{subscription_id}/cancel")
def cancel_subscription_request(business_id: int, subscription_id: int, db: Session = Depends(get_db),
                               actor: User = Depends(get_current_user)):
    """Cancel an unpaid request so the shop can choose another plan."""
    sub = authorized_subscription(db, actor, business_id, subscription_id)
    sub = db.scalar(select(Subscription).where(Subscription.id == sub.id)
                    .with_for_update().execution_options(populate_existing=True))
    if sub.status == "cancelled":
        return {"id": sub.id, "status": sub.status}
    if sub.status not in {"awaiting_payment", "pending"}:
        raise HTTPException(409, "Chỉ có thể hủy yêu cầu chưa được duyệt.")
    attempt = get_attempt(db, sub.id)
    if paid_receipt(db, sub) is not None or (attempt is not None and (
        attempt.status in {"paid", "refunded", "reconciliation_required"} or attempt.reconciliation_required
    )):
        raise HTTPException(409, "Đã có giao dịch hoặc cần đối soát; vui lòng liên hệ quản trị viên để xử lý.")
    previous_status = sub.status
    sub.status = "cancelled"
    record_audit(
        db,
        business_id=business_id,
        user_id=actor.id,
        action="subscription_payment_request_cancelled",
        resource_type="subscription",
        resource_id=sub.id,
        metadata={"previous_status": previous_status},
    )
    db.commit()
    return {"id": sub.id, "status": sub.status}


@router.post("/webhooks/payos")
def payos_webhook(payload: dict, db: Session = Depends(get_db)):
    return receive_webhook(db, payload)
