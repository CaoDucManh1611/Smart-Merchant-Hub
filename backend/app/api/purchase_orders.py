"""Tenant-scoped purchase orders and explicit procurement lifecycle."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db.dependencies import get_db
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.business import User
from app.models.sales import Product
from app.schemas.purchase_order import (
    PurchaseOrderCreate,
    PurchaseOrderItemOut,
    PurchaseOrderListOut,
    PurchaseOrderOut,
    PurchaseOrderTransition,
    PurchaseOrderUpdate,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.auth.dependencies import require_write_access
from app.services.audit_service import record_audit


router = APIRouter()

PURCHASE_TRANSITIONS = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"partially_received", "received", "cancelled"},
    "partially_received": {"received", "cancelled"},
    "received": {"closed"},
    "closed": set(),
    "cancelled": set(),
}


def _purchase_order(db: Session, order_id: int, tenant: TenantContext) -> PurchaseOrder:
    order = db.query(PurchaseOrder).options(
        joinedload(PurchaseOrder.items).joinedload(PurchaseOrderItem.product),
    ).filter(
        PurchaseOrder.id == order_id,
        PurchaseOrder.business_id == tenant.business_id,
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Purchase Order không tồn tại.")
    return order


def _out(order: PurchaseOrder) -> PurchaseOrderOut:
    return PurchaseOrderOut(
        id=order.id,
        business_id=order.business_id,
        po_number=order.po_number,
        supplier_name=order.supplier_name,
        status=order.status,
        total_spend=order.total_spend,
        notes=order.notes,
        metadata=order.metadata_,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[PurchaseOrderItemOut(
            id=item.id,
            product_id=item.product_id,
            product_name=item.product.name,
            quantity=item.quantity,
            unit_cost=item.unit_cost,
            line_total=item.line_total,
        ) for item in order.items],
    )


@router.get("/purchase-orders", response_model=PurchaseOrderListOut)
def list_purchase_orders(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    status: str | None = Query(default=None, max_length=30),
    supplier: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(PurchaseOrder).filter(PurchaseOrder.business_id == tenant.business_id)
    if status:
        query = query.filter(PurchaseOrder.status == status.strip())
    if supplier:
        query = query.filter(PurchaseOrder.supplier_name.ilike(f"%{supplier.strip()}%"))
    total = query.count()
    orders = query.options(
        joinedload(PurchaseOrder.items).joinedload(PurchaseOrderItem.product),
    ).order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc()).offset(offset).limit(limit).all()
    return PurchaseOrderListOut(items=[_out(order) for order in orders], total=total)


@router.post("/purchase-orders", response_model=PurchaseOrderOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_purchase_order(
    payload: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    product_ids = [item.product_id for item in payload.items]
    products = db.query(Product).filter(
        Product.business_id == tenant.business_id,
        Product.id.in_(product_ids),
    ).all()
    product_map = {product.id: product for product in products}
    missing = [product_id for product_id in product_ids if product_id not in product_map]
    if missing:
        raise HTTPException(status_code=404, detail=f"Sản phẩm không tồn tại trong tenant: {missing}")
    status = payload.status.strip().lower()
    if status not in PURCHASE_TRANSITIONS:
        raise HTTPException(status_code=422, detail="Trạng thái Purchase Order không hợp lệ.")
    order = PurchaseOrder(
        business_id=tenant.business_id,
        po_number=payload.po_number.strip(),
        supplier_name=payload.supplier_name.strip(),
        status=status,
        notes=payload.notes,
        metadata_=payload.metadata,
        total_spend=Decimal("0"),
    )
    db.add(order)
    db.flush()
    total = Decimal("0")
    for item_payload in payload.items:
        line_total = item_payload.unit_cost * item_payload.quantity
        total += line_total
        db.add(PurchaseOrderItem(
            purchase_order_id=order.id,
            product_id=product_map[item_payload.product_id].id,
            quantity=item_payload.quantity,
            unit_cost=item_payload.unit_cost,
            line_total=line_total,
        ))
    order.total_spend = total
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mã Purchase Order đã tồn tại trong business này.") from exc
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="create", resource_type="purchase_order", resource_id=str(order.id), metadata={"po_number": order.po_number, "supplier_name": order.supplier_name, "total_spend": float(order.total_spend or 0)})
        db.commit()
    return _out(_purchase_order(db, order.id, tenant))


@router.get("/purchase-orders/{order_id}", response_model=PurchaseOrderOut)
def get_purchase_order(order_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    return _out(_purchase_order(db, order_id, tenant))


@router.patch("/purchase-orders/{order_id}", response_model=PurchaseOrderOut, dependencies=[Depends(require_write_access)])
def update_purchase_order(
    order_id: int,
    payload: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    order = _purchase_order(db, order_id, tenant)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(order, "metadata_" if field == "metadata" else field, value.strip() if isinstance(value, str) else value)
    db.commit()
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="update", resource_type="purchase_order", resource_id=str(order.id), metadata={"fields": list(payload.model_dump(exclude_unset=True))})
        db.commit()
    return _out(_purchase_order(db, order_id, tenant))


@router.post("/purchase-orders/{order_id}/transition", response_model=PurchaseOrderOut, dependencies=[Depends(require_write_access)])
def transition_purchase_order(
    order_id: int,
    payload: PurchaseOrderTransition,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    order = _purchase_order(db, order_id, tenant)
    to_status = payload.to_status.strip().lower()
    if to_status not in PURCHASE_TRANSITIONS:
        raise HTTPException(status_code=422, detail="Trạng thái Purchase Order không hợp lệ.")
    if to_status not in PURCHASE_TRANSITIONS.get(order.status, set()):
        raise HTTPException(status_code=409, detail=f"Không thể chuyển {order.status} sang {to_status}.")
    order.status = to_status
    db.commit()
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="transition", resource_type="purchase_order", resource_id=str(order.id), metadata={"to_status": to_status})
        db.commit()
    return _out(_purchase_order(db, order_id, tenant))
