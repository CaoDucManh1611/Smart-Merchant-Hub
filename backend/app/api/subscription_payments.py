from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.onboarding import _require_shop_member_for_purchase
from app.auth.dependencies import get_current_user
from app.db.dependencies import get_db
from app.models.business import Subscription, User
from app.schemas.subscription_payment import SubscriptionPaymentOut
from app.services.subscription_payment_service import payment_status, receive_webhook
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


@router.post("/webhooks/payos")
def payos_webhook(payload: dict, db: Session = Depends(get_db)):
    return receive_webhook(db, payload)
