"""Transactional Sales Order lifecycle and inventory reservation rules."""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from app.models.inventory import StockMovement
from app.models.order_event import OrderEvent
from app.models.sales import Order, OrderItem, Product


SALES_TRANSITIONS = {
    "draft": {"confirmed", "cancelled"},
    "confirmed": {"processing", "cancelled"},
    "processing": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    "delivered": {"completed", "refunded"},
    "completed": set(),
    "refunded": set(),
    "cancelled": set(),
}


class SalesOrderOperationError(ValueError):
    """A controlled Sales Order lifecycle error."""

    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def transition_sales_order(
    db: Session,
    *,
    order_id: int,
    to_status: str,
    actor_id: int | None,
    business_id: int,
) -> Order:
    """Apply one Sales Order transition and its inventory effects.

    The caller owns the transaction boundary. Product rows are locked in
    deterministic order before changing stock or reservations.
    """
    order = db.query(Order).options(
        joinedload(Order.items),
    ).filter(
        Order.id == order_id,
        Order.business_id == business_id,
    ).with_for_update().first()
    if order is None:
        raise SalesOrderOperationError("Đơn hàng không tồn tại.", 404)

    target = to_status.strip().lower()
    if target not in SALES_TRANSITIONS:
        raise SalesOrderOperationError("Trạng thái đơn hàng không hợp lệ.", 422)
    allowed = SALES_TRANSITIONS.get(order.status, set())
    if target not in allowed:
        raise SalesOrderOperationError(f"Không thể chuyển {order.status} sang {target}.", 409)
    previous = order.status

    product_ids = sorted({item.product_id for item in order.items})
    products = db.query(Product).filter(
        Product.business_id == business_id,
        Product.id.in_(product_ids),
    ).order_by(Product.id.asc()).with_for_update().all()
    product_map = {product.id: product for product in products}
    missing = [product_id for product_id in product_ids if product_id not in product_map]
    if missing:
        raise SalesOrderOperationError(f"Sản phẩm không tồn tại trong business: {missing}.", 404)

    if target == "confirmed":
        for item in order.items:
            product = product_map[item.product_id]
            stock = int(product.stock_quantity or 0)
            reserved = int(product.reserved_quantity or 0)
            available = stock - reserved
            if available < item.quantity:
                raise SalesOrderOperationError(
                    f"Sản phẩm {product.sku} không đủ tồn khả dụng ({available}).",
                    409,
                )
        total_reserved = 0
        for item in order.items:
            product = product_map[item.product_id]
            product.reserved_quantity = int(product.reserved_quantity or 0) + item.quantity
            total_reserved += item.quantity
        order.reserved_quantity = total_reserved

    elif target == "shipped":
        for item in order.items:
            product = product_map[item.product_id]
            stock = int(product.stock_quantity or 0)
            reserved = int(product.reserved_quantity or 0)
            if reserved < item.quantity or stock < item.quantity:
                raise SalesOrderOperationError(
                    f"Không thể xuất kho sản phẩm {product.sku}: tồn/giữ không đủ.",
                    409,
                )
        for item in order.items:
            product = product_map[item.product_id]
            before = int(product.stock_quantity or 0)
            product.stock_quantity = before - item.quantity
            product.reserved_quantity = int(product.reserved_quantity or 0) - item.quantity
            db.add(StockMovement(
                business_id=business_id,
                product_id=product.id,
                movement_type="sales_shipment",
                quantity=-item.quantity,
                quantity_before=before,
                quantity_after=product.stock_quantity,
                source_type="sales_order",
                source_id=order.id,
                actor_id=actor_id,
            ))
        order.reserved_quantity = 0

    elif target == "cancelled" and previous in {"confirmed", "processing"}:
        for item in order.items:
            product = product_map[item.product_id]
            reserved = int(product.reserved_quantity or 0)
            if reserved < item.quantity:
                raise SalesOrderOperationError(
                    f"Không thể giải phóng tồn giữ cho sản phẩm {product.sku}.",
                    409,
                )
        for item in order.items:
            product = product_map[item.product_id]
            product.reserved_quantity = int(product.reserved_quantity or 0) - item.quantity
        order.reserved_quantity = 0

    elif target == "refunded":
        for item in order.items:
            product = product_map[item.product_id]
            before = int(product.stock_quantity or 0)
            product.stock_quantity = before + item.quantity
            db.add(StockMovement(
                business_id=business_id,
                product_id=product.id,
                movement_type="sales_refund",
                quantity=item.quantity,
                quantity_before=before,
                quantity_after=product.stock_quantity,
                source_type="sales_order",
                source_id=order.id,
                actor_id=actor_id,
            ))

    order.status = target
    db.add(OrderEvent(
        business_id=business_id,
        order_type="sales_order",
        order_id=order.id,
        event_type="status_changed",
        from_status=previous,
        to_status=target,
        actor_id=actor_id,
        metadata_={"reserved_quantity": int(order.reserved_quantity or 0)},
    ))
    return order
