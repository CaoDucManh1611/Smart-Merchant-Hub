"""Payment, refund and append-only order-event endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.purchase_orders import _out as purchase_order_out
from app.api.purchase_orders import _purchase_order
from app.api.sales import _order, _order_out
from app.auth.dependencies import require_write_access
from app.db.dependencies import get_db
from app.models.business import User
from app.models.order_event import OrderEvent
from app.models.order_payment import OrderPayment
from app.schemas.payment import (
    OrderEventListOut,
    OrderEventOut,
    PaymentCreate,
    PaymentListOut,
    PaymentOut,
    PaymentResult,
    PurchasePaymentResult,
    RefundCreate,
    SalesPaymentResult,
)
from app.services.audit_service import record_audit
from app.services.order_service import (
    PaymentOperationError,
    record_order_payment,
    record_purchase_payment,
    refund_order_payment,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter()


def _payment_list(db: Session, *, business_id: int, order_id: int | None = None, purchase_order_id: int | None = None):
    query = db.query(OrderPayment).filter(OrderPayment.business_id == business_id)
    if order_id is not None:
        query = query.filter(OrderPayment.order_id == order_id)
    if purchase_order_id is not None:
        query = query.filter(OrderPayment.purchase_order_id == purchase_order_id)
    total = query.count()
    return query.order_by(OrderPayment.created_at.asc(), OrderPayment.id.asc()).all(), total


def _events(db: Session, *, business_id: int, order_type: str, order_id: int):
    query = db.query(OrderEvent).filter(
        OrderEvent.business_id == business_id,
        OrderEvent.order_type == order_type,
        OrderEvent.order_id == order_id,
    )
    rows = query.order_by(OrderEvent.created_at.desc(), OrderEvent.id.desc()).all()
    return OrderEventListOut(items=[OrderEventOut.model_validate(row) for row in rows], total=len(rows))


def _replayed_payment(
    db: Session,
    *,
    business_id: int,
    idempotency_key: str,
    order_id: int | None = None,
    purchase_order_id: int | None = None,
) -> OrderPayment:
    payment = db.query(OrderPayment).filter(
        OrderPayment.business_id == business_id,
        OrderPayment.idempotency_key == idempotency_key.strip(),
    ).first()
    if payment is None or payment.order_id != order_id or payment.purchase_order_id != purchase_order_id:
        raise HTTPException(status_code=409, detail="Idempotency key đã được dùng cho giao dịch khác.")
    return payment


@router.post("/orders/{order_id}/payments", response_model=SalesPaymentResult, dependencies=[Depends(require_write_access)])
def create_order_payment(
    order_id: int,
    payload: PaymentCreate,
    response: Response,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    try:
        payment, _, created = record_order_payment(
            db,
            order_id=order_id,
            amount=payload.amount,
            method=payload.method,
            status=payload.status,
            reference=payload.reference,
            idempotency_key=payload.idempotency_key,
            actor_id=actor.id if actor else None,
            business_id=tenant.business_id,
        )
    except PaymentOperationError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except IntegrityError:
        db.rollback()
        payment = _replayed_payment(
            db,
            business_id=tenant.business_id,
            idempotency_key=payload.idempotency_key,
            order_id=order_id,
        )
        created = False
    if created:
        db.commit()
        response.status_code = 201
        if actor:
            record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="create", resource_type="order_payment", resource_id=str(payment.id), metadata={"order_id": order_id, "amount": str(payload.amount), "method": payload.method, "status": payload.status})
            db.commit()
    else:
        response.status_code = 200
    order = _order(db, order_id, tenant)
    payment = db.query(OrderPayment).filter(OrderPayment.id == payment.id, OrderPayment.business_id == tenant.business_id).first()
    return {"payment": payment, "order": _order_out(order)}


@router.post("/orders/{order_id}/refunds", response_model=SalesPaymentResult, dependencies=[Depends(require_write_access)])
def create_order_refund(
    order_id: int,
    payload: RefundCreate,
    response: Response,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    try:
        payment, _, created = refund_order_payment(
            db,
            order_id=order_id,
            amount=payload.amount,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
            actor_id=actor.id if actor else None,
            business_id=tenant.business_id,
        )
    except PaymentOperationError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except IntegrityError:
        db.rollback()
        payment = _replayed_payment(
            db,
            business_id=tenant.business_id,
            idempotency_key=payload.idempotency_key,
            order_id=order_id,
        )
        created = False
    if created:
        db.commit()
        response.status_code = 201
        if actor:
            record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="refund", resource_type="order_payment", resource_id=str(payment.id), metadata={"order_id": order_id, "amount": str(payload.amount)})
            db.commit()
    else:
        response.status_code = 200
    order = _order(db, order_id, tenant)
    payment = db.query(OrderPayment).filter(OrderPayment.id == payment.id, OrderPayment.business_id == tenant.business_id).first()
    return {"payment": payment, "order": _order_out(order)}


@router.get("/orders/{order_id}/payments", response_model=PaymentListOut)
def list_order_payments(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    _order(db, order_id, tenant)
    rows, total = _payment_list(db, business_id=tenant.business_id, order_id=order_id)
    return PaymentListOut(items=[PaymentOut.model_validate(row) for row in rows], total=total)


@router.post("/purchase-orders/{order_id}/payments", response_model=PurchasePaymentResult, dependencies=[Depends(require_write_access)])
def create_purchase_order_payment(
    order_id: int,
    payload: PaymentCreate,
    response: Response,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    try:
        payment, _, created = record_purchase_payment(
            db,
            purchase_order_id=order_id,
            amount=payload.amount,
            method=payload.method,
            status=payload.status,
            reference=payload.reference,
            idempotency_key=payload.idempotency_key,
            actor_id=actor.id if actor else None,
            business_id=tenant.business_id,
        )
    except PaymentOperationError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except IntegrityError:
        db.rollback()
        payment = _replayed_payment(
            db,
            business_id=tenant.business_id,
            idempotency_key=payload.idempotency_key,
            purchase_order_id=order_id,
        )
        created = False
    if created:
        db.commit()
        response.status_code = 201
        if actor:
            record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="create", resource_type="purchase_order_payment", resource_id=str(payment.id), metadata={"purchase_order_id": order_id, "amount": str(payload.amount), "method": payload.method, "status": payload.status})
            db.commit()
    else:
        response.status_code = 200
    order = _purchase_order(db, order_id, tenant)
    payment = db.query(OrderPayment).filter(OrderPayment.id == payment.id, OrderPayment.business_id == tenant.business_id).first()
    return {"payment": payment, "order": purchase_order_out(order)}


@router.get("/purchase-orders/{order_id}/payments", response_model=PaymentListOut)
def list_purchase_order_payments(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    _purchase_order(db, order_id, tenant)
    rows, total = _payment_list(db, business_id=tenant.business_id, purchase_order_id=order_id)
    return PaymentListOut(items=[PaymentOut.model_validate(row) for row in rows], total=total)


@router.get("/orders/{order_id}/events", response_model=OrderEventListOut)
def list_order_events(order_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    _order(db, order_id, tenant)
    return _events(db, business_id=tenant.business_id, order_type="sales_order", order_id=order_id)


@router.get("/purchase-orders/{order_id}/events", response_model=OrderEventListOut)
def list_purchase_order_events(order_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    _purchase_order(db, order_id, tenant)
    return _events(db, business_id=tenant.business_id, order_type="purchase_order", order_id=order_id)
