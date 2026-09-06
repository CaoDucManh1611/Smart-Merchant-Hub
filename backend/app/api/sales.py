"""Tenant-scoped product catalog and order APIs."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db.dependencies import get_db
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.sales import Order, OrderItem, Product
from app.models.business import User
from app.schemas.sales import (
    OrderCreate,
    OrderItemOut,
    OrderListOut,
    OrderOut,
    OrderUpdate,
    OrderTransition,
    ProductCreate,
    ProductListOut,
    ProductOut,
    ProductUpdate,
    RevenueByChannelOut,
    RevenueChannelItem,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.services.workflow_engine import emit_workflow_event
from app.auth.dependencies import require_write_access
from app.services.audit_service import record_audit
from app.services.order_service import SalesOrderOperationError, SALES_TRANSITIONS as ORDER_TRANSITIONS, transition_sales_order


router = APIRouter()

SALES_TRANSITIONS = ORDER_TRANSITIONS


def _generated_order_number(db: Session, business_id: int) -> str:
    """Generate a readable, tenant-scoped order number for API clients."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    base = f"ORD-{timestamp}"
    candidate = base
    sequence = 1
    while db.query(Order.id).filter(
        Order.business_id == business_id,
        Order.order_number == candidate,
    ).first() is not None:
        sequence += 1
        candidate = f"{base}-{sequence}"
    return candidate


def _product(db: Session, product_id: int, tenant: TenantContext) -> Product:
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.business_id == tenant.business_id,
    ).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại.")
    return product


def _order(db: Session, order_id: int, tenant: TenantContext) -> Order:
    order = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.product),
        joinedload(Order.conversation),
    ).filter(
        Order.id == order_id,
        Order.business_id == tenant.business_id,
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Đơn hàng không tồn tại.")
    return order


def _order_out(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        business_id=order.business_id,
        customer_id=order.customer_id,
        conversation_id=order.conversation_id,
        channel=order.conversation.channel if order.conversation else None,
        order_number=order.order_number,
        status=order.status,
        total_amount=order.total_amount,
        reserved_quantity=int(order.reserved_quantity or 0),
        payment_status=order.payment_status,
        paid_amount=order.paid_amount,
        refunded_amount=order.refunded_amount,
        cancel_reason=order.cancel_reason,
        shipping_address=order.shipping_address,
        shipping_phone=order.shipping_phone,
        metadata=order.metadata_,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[OrderItemOut(
            id=item.id,
            product_id=item.product_id,
            product_name=item.product.name,
            quantity=item.quantity,
            unit_price=item.unit_price,
            line_total=item.line_total,
            product_name_snapshot=item.product_name_snapshot,
            sku_snapshot=item.sku_snapshot,
        ) for item in order.items],
    )


@router.get("/products", response_model=ProductListOut)
def list_products(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(Product).filter(Product.business_id == tenant.business_id)
    if status:
        query = query.filter(Product.status == status)
    total = query.count()
    products = query.order_by(Product.name.asc(), Product.id.asc()).offset(offset).limit(limit).all()
    return ProductListOut(items=[ProductOut.model_validate(product) for product in products], total=total)


@router.post("/products", response_model=ProductOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    product = Product(
        business_id=tenant.business_id,
        sku=payload.sku.strip(),
        name=payload.name.strip(),
        description=payload.description,
        price=payload.price,
        stock_quantity=payload.stock_quantity,
        status=payload.status,
        metadata_=payload.metadata,
    )
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="SKU đã tồn tại trong business này.") from exc
    db.refresh(product)
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="create", resource_type="product", resource_id=str(product.id), metadata={"sku": product.sku})
        db.commit()
    return product


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return _product(db, product_id, tenant)


@router.patch("/products/{product_id}", response_model=ProductOut, dependencies=[Depends(require_write_access)])
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    product = _product(db, product_id, tenant)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, "metadata_" if field == "metadata" else field, value.strip() if isinstance(value, str) else value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="SKU đã tồn tại trong business này.") from exc
    db.refresh(product)
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="update", resource_type="product", resource_id=str(product.id), metadata={"fields": list(payload.model_dump(exclude_unset=True))})
        db.commit()
    return product


@router.delete("/products/{product_id}", status_code=204, dependencies=[Depends(require_write_access)])
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    product = _product(db, product_id, tenant)
    product.status = "archived"
    db.commit()
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="archive", resource_type="product", resource_id=str(product.id))
        db.commit()


@router.get("/orders", response_model=OrderListOut)
def list_orders(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    status: str | None = None,
    customer_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.product),
        joinedload(Order.conversation),
    ).filter(
        Order.business_id == tenant.business_id,
    )
    if status:
        query = query.filter(Order.status == status)
    if customer_id is not None:
        query = query.filter(Order.customer_id == customer_id)
    total = query.count()
    orders = query.order_by(Order.created_at.desc(), Order.id.desc()).offset(offset).limit(limit).all()
    return OrderListOut(items=[_order_out(order) for order in orders], total=total)


@router.get("/reports/revenue-by-channel", response_model=RevenueByChannelOut)
def revenue_by_channel(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Aggregate tenant orders by the channel of their originating conversation.

    Orders without a linked conversation remain visible under ``unknown`` so the
    report never silently drops revenue. Both the order and conversation are
    constrained to the active tenant.
    """
    channel_expr = func.coalesce(Conversation.channel, "unknown")
    rows = (
        db.query(
            channel_expr.label("channel"),
            func.count(Order.id).label("order_count"),
            func.coalesce(func.sum(Order.total_amount), Decimal("0")).label("revenue"),
        )
        .outerjoin(
            Conversation,
            (Conversation.id == Order.conversation_id)
            & (Conversation.business_id == tenant.business_id),
        )
        .filter(Order.business_id == tenant.business_id)
        .group_by(channel_expr)
        .order_by(channel_expr.asc())
        .all()
    )
    items = [RevenueChannelItem(
        channel=str(row.channel),
        order_count=int(row.order_count),
        revenue=Decimal(row.revenue or 0),
    ) for row in rows]
    return RevenueByChannelOut(
        items=items,
        total_revenue=sum((item.revenue for item in items), Decimal("0")),
    )


@router.post("/orders", response_model=OrderOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    customer = db.query(Customer).filter(
        Customer.id == payload.customer_id,
        Customer.business_id == tenant.business_id,
    ).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer không tồn tại.")

    conversation = None
    if payload.conversation_id is not None:
        conversation = db.query(Conversation).filter(
            Conversation.id == payload.conversation_id,
            Conversation.business_id == tenant.business_id,
            Conversation.customer_id == payload.customer_id,
        ).first()
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation không thuộc customer/business này.")

    product_ids = [item.product_id for item in payload.items]
    products = db.query(Product).filter(
        Product.business_id == tenant.business_id,
        Product.id.in_(product_ids),
    ).all()
    product_map = {product.id: product for product in products}
    missing = [product_id for product_id in product_ids if product_id not in product_map]
    if missing:
        raise HTTPException(status_code=404, detail=f"Sản phẩm không tồn tại trong tenant: {missing}")

    order_number = (payload.order_number or "").strip()
    if not order_number:
        order_number = _generated_order_number(db, tenant.business_id)

    order = Order(
        business_id=tenant.business_id,
        customer_id=customer.id,
        conversation_id=conversation.id if conversation else None,
        order_number=order_number,
        status=payload.status,
        shipping_address=payload.shipping_address,
        shipping_phone=payload.shipping_phone,
        metadata_=payload.metadata,
        total_amount=Decimal("0"),
    )
    db.add(order)
    db.flush()
    total = Decimal("0")
    for item_payload in payload.items:
        product = product_map[item_payload.product_id]
        unit_price = Decimal(product.price)
        line_total = unit_price * item_payload.quantity
        total += line_total
        db.add(OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=item_payload.quantity,
            unit_price=unit_price,
            line_total=line_total,
            product_name_snapshot=product.name,
            sku_snapshot=product.sku,
        ))
    order.total_amount = total
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mã đơn hàng đã tồn tại trong business này.") from exc
    emit_workflow_event(
        db,
        tenant,
        "order.created",
        f"order:{order.id}:created",
        {"order_id": order.id, "customer_id": order.customer_id, "conversation_id": order.conversation_id, "status": order.status, "total_amount": float(order.total_amount or 0)},
    )
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="create", resource_type="sales_order", resource_id=str(order.id), metadata={"order_number": order.order_number, "total_amount": float(order.total_amount or 0)})
        db.commit()
    return _order_out(_order(db, order.id, tenant))


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return _order_out(_order(db, order_id, tenant))


@router.patch("/orders/{order_id}", response_model=OrderOut, dependencies=[Depends(require_write_access)])
def update_order(
    order_id: int,
    payload: OrderUpdate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    order = _order(db, order_id, tenant)
    values = payload.model_dump(exclude_unset=True)
    if "status" in values:
        raise HTTPException(status_code=409, detail="Trạng thái đơn phải đổi qua endpoint transition để cập nhật tồn kho.")
    for field, value in values.items():
        setattr(order, "metadata_" if field == "metadata" else field, value)
    db.commit()
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="update", resource_type="sales_order", resource_id=str(order.id), metadata={"fields": list(payload.model_dump(exclude_unset=True))})
        db.commit()
    return _order_out(_order(db, order_id, tenant))


@router.post("/orders/{order_id}/transition", response_model=OrderOut, dependencies=[Depends(require_write_access)])
def transition_order(
    order_id: int,
    payload: OrderTransition,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    try:
        transition_sales_order(
            db,
            order_id=order_id,
            to_status=payload.to_status,
            actor_id=actor.id if actor else None,
            business_id=tenant.business_id,
        )
        db.commit()
    except SalesOrderOperationError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    order = _order(db, order_id, tenant)
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="transition", resource_type="sales_order", resource_id=str(order.id), metadata={"to_status": order.status})
        db.commit()
    return _order_out(_order(db, order_id, tenant))
