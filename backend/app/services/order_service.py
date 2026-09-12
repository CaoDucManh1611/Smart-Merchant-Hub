"""Transactional Sales Order lifecycle and inventory reservation rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.inventory import StockMovement
from app.models.order_event import OrderEvent
from app.models.order_payment import OrderPayment
from app.models.purchase_order import PurchaseOrder
from app.models.sales import Order, OrderItem, Product
from app.services.audit_service import record_audit


SALES_TRANSITIONS = {
    "draft": {"confirmed", "cancelled"},
    "confirmed": {"processing", "cancelled"},
    "processing": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    # A refund is a monetary operation, never a free-form status change.
    # The refund endpoint changes a fully returned delivered/completed order
    # to ``refunded`` only after it records the immutable refund payment.
    "delivered": {"completed"},
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


class PaymentOperationError(ValueError):
    """A controlled payment/refund validation error."""

    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


PAYMENT_STATUSES = {"pending", "paid", "failed", "cancelled"}
DRAFT_RESERVATION_TTL = timedelta(hours=2)


def _payment_status(paid: Decimal, total: Decimal, refunded: Decimal = Decimal("0")) -> str:
    if paid <= 0:
        return "unpaid"
    net_paid = paid - refunded
    if net_paid <= 0:
        return "refunded" if refunded > 0 else "unpaid"
    if net_paid >= total:
        return "paid"
    return "partial"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sales_order_items(db: Session, order_id: int) -> list[OrderItem]:
    return db.query(OrderItem).filter(
        OrderItem.order_id == order_id,
    ).order_by(OrderItem.id.asc()).all()


def _quantities_by_product(items: list[OrderItem]) -> dict[int, int]:
    quantities: dict[int, int] = {}
    for item in items:
        quantities[item.product_id] = quantities.get(item.product_id, 0) + int(item.quantity or 0)
    return quantities


def reserve_draft_order_inventory(
    db: Session,
    *,
    order: Order,
    business_id: int,
    expires_at: datetime | None = None,
) -> Order:
    """Hold stock for a chatbot draft without decrementing on-hand inventory.

    The operation is idempotent for an already-held draft.  Confirmation can
    therefore reuse the reservation instead of incrementing product holds a
    second time.
    """
    if order.status != "draft":
        raise SalesOrderOperationError("Chỉ đơn nháp mới được giữ tồn tạm thời.", 409)
    metadata = dict(order.metadata_ or {})
    if metadata.get("reservation_status") == "held" and int(order.reserved_quantity or 0) > 0:
        return order

    items = _sales_order_items(db, order.id)
    quantities = _quantities_by_product(items)
    if not quantities:
        raise SalesOrderOperationError("Đơn nháp chưa có sản phẩm để giữ tồn.", 422)
    products = db.query(Product).filter(
        Product.business_id == business_id,
        Product.id.in_(sorted(quantities)),
    ).order_by(Product.id.asc()).with_for_update().all()
    product_map = {product.id: product for product in products}
    missing = [product_id for product_id in quantities if product_id not in product_map]
    if missing:
        raise SalesOrderOperationError(f"Sản phẩm không tồn tại trong business: {missing}.", 404)
    for product_id, quantity in quantities.items():
        product = product_map[product_id]
        available = int(product.stock_quantity or 0) - int(product.reserved_quantity or 0)
        if available < quantity:
            raise SalesOrderOperationError(
                f"Sản phẩm {product.sku} không đủ tồn khả dụng ({available}).",
                409,
            )
    for product_id, quantity in quantities.items():
        product = product_map[product_id]
        product.reserved_quantity = int(product.reserved_quantity or 0) + quantity

    deadline = expires_at or (_now() + DRAFT_RESERVATION_TTL)
    if deadline.tzinfo is not None:
        deadline = deadline.astimezone(timezone.utc).replace(tzinfo=None)
    order.reserved_quantity = sum(quantities.values())
    order.reservation_expires_at = deadline
    metadata.update({
        "reservation_status": "held",
        "reservation_expires_at": deadline.isoformat(),
    })
    order.metadata_ = metadata
    db.add(OrderEvent(
        business_id=business_id,
        order_type="sales_order",
        order_id=order.id,
        event_type="reservation_created",
        metadata_={"reserved_quantity": order.reserved_quantity, "expires_at": deadline.isoformat()},
    ))
    return order


def release_draft_order_reservation(
    db: Session,
    *,
    order_id: int,
    business_id: int,
    reason: str = "expired",
) -> Order | None:
    """Release a draft's held stock while retaining the draft for audit/history."""
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.business_id == business_id,
    ).with_for_update().first()
    if order is None or order.status != "draft" or int(order.reserved_quantity or 0) <= 0:
        return order

    quantities = _quantities_by_product(_sales_order_items(db, order.id))
    products = db.query(Product).filter(
        Product.business_id == business_id,
        Product.id.in_(sorted(quantities)),
    ).order_by(Product.id.asc()).with_for_update().all()
    product_map = {product.id: product for product in products}
    missing = [product_id for product_id in quantities if product_id not in product_map]
    if missing:
        raise SalesOrderOperationError(f"Sản phẩm không tồn tại trong business: {missing}.", 404)
    for product_id, quantity in quantities.items():
        product = product_map[product_id]
        reserved = int(product.reserved_quantity or 0)
        if reserved < quantity:
            raise SalesOrderOperationError(
                f"Sản phẩm {product.sku} không đủ tồn giữ để giải phóng.",
                409,
            )
    for product_id, quantity in quantities.items():
        product_map[product_id].reserved_quantity = int(product_map[product_id].reserved_quantity or 0) - quantity

    metadata = dict(order.metadata_ or {})
    metadata.update({
        "reservation_status": reason,
        "reservation_released_at": _now().isoformat(),
    })
    order.metadata_ = metadata
    order.reserved_quantity = 0
    order.reservation_expires_at = None
    db.add(OrderEvent(
        business_id=business_id,
        order_type="sales_order",
        order_id=order.id,
        event_type="reservation_released",
        metadata_={"reason": reason},
    ))
    record_audit(
        db,
        business_id=business_id,
        actor_type="system",
        action="sales_draft_reservation_released",
        resource_type="sales_order",
        resource_id=order.id,
        metadata={"reason": reason},
    )
    return order


def release_expired_draft_reservations(
    db: Session,
    business_id: int,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> int:
    """Release expired draft holds for one tenant; safe to call every worker tick."""
    current = now or _now()
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    order_ids = [row[0] for row in db.query(Order.id).filter(
        Order.business_id == business_id,
        Order.status == "draft",
        Order.reserved_quantity > 0,
        Order.reservation_expires_at.is_not(None),
        Order.reservation_expires_at <= current,
    ).order_by(Order.reservation_expires_at.asc(), Order.id.asc()).limit(max(1, min(int(limit), 500))).all()]
    released = 0
    for order_id in order_ids:
        order = release_draft_order_reservation(
            db,
            order_id=int(order_id),
            business_id=business_id,
            reason="expired",
        )
        if order is not None and order.reserved_quantity == 0:
            released += 1
    return released


def _existing_payment(
    db: Session,
    *,
    business_id: int,
    idempotency_key: str,
    order_id: int | None = None,
    purchase_order_id: int | None = None,
) -> OrderPayment | None:
    existing = db.query(OrderPayment).filter(
        OrderPayment.business_id == business_id,
        OrderPayment.idempotency_key == idempotency_key,
    ).first()
    if existing is None:
        return None
    if existing.order_id != order_id or existing.purchase_order_id != purchase_order_id:
        raise PaymentOperationError("Idempotency key đã được dùng cho giao dịch khác.", 409)
    return existing


def record_order_payment(
    db: Session,
    *,
    order_id: int,
    amount: Decimal,
    method: str,
    status: str,
    reference: str | None,
    idempotency_key: str,
    actor_id: int | None,
    business_id: int,
) -> tuple[OrderPayment, Order, bool]:
    """Record a customer payment and update the order's payment summary."""
    existing = _existing_payment(
        db,
        business_id=business_id,
        idempotency_key=idempotency_key,
        order_id=order_id,
    )
    if existing is not None:
        order = db.query(Order).filter(Order.id == order_id, Order.business_id == business_id).first()
        if order is None:
            raise PaymentOperationError("Đơn hàng không tồn tại.", 404)
        return existing, order, False

    order = db.query(Order).filter(
        Order.id == order_id,
        Order.business_id == business_id,
    ).with_for_update().first()
    if order is None:
        raise PaymentOperationError("Đơn hàng không tồn tại.", 404)
    normalized_status = status.strip().lower()
    if normalized_status not in PAYMENT_STATUSES:
        raise PaymentOperationError("Trạng thái thanh toán không hợp lệ.", 422)
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if normalized_status == "paid":
        new_paid = Decimal(order.paid_amount or 0) + amount
        if new_paid > Decimal(order.total_amount or 0):
            raise PaymentOperationError("Số tiền thanh toán vượt quá giá trị đơn hàng.", 409)
        order.paid_amount = new_paid
        order.payment_status = _payment_status(new_paid, Decimal(order.total_amount or 0), Decimal(order.refunded_amount or 0))
    payment = OrderPayment(
        business_id=business_id,
        order_id=order.id,
        amount=amount,
        method=method.strip(),
        status=normalized_status,
        reference=reference.strip() if reference else None,
        paid_at=datetime.now(timezone.utc).replace(tzinfo=None) if normalized_status == "paid" else None,
        idempotency_key=idempotency_key.strip(),
    )
    db.add(payment)
    db.flush()
    db.add(OrderEvent(
        business_id=business_id,
        order_type="sales_order",
        order_id=order.id,
        event_type="payment_created",
        actor_id=actor_id,
        metadata_={"payment_id": payment.id, "amount": str(amount), "method": payment.method, "status": normalized_status},
    ))
    return payment, order, True


def refund_order_payment(
    db: Session,
    *,
    order_id: int,
    amount: Decimal,
    reason: str | None,
    idempotency_key: str,
    actor_id: int | None,
    business_id: int,
) -> tuple[OrderPayment, Order, bool]:
    """Record a customer refund without allowing refunds beyond paid money."""
    existing = _existing_payment(
        db,
        business_id=business_id,
        idempotency_key=idempotency_key,
        order_id=order_id,
    )
    if existing is not None:
        order = db.query(Order).filter(Order.id == order_id, Order.business_id == business_id).first()
        if order is None:
            raise PaymentOperationError("Đơn hàng không tồn tại.", 404)
        return existing, order, False

    order = db.query(Order).filter(
        Order.id == order_id,
        Order.business_id == business_id,
    ).with_for_update().first()
    if order is None:
        raise PaymentOperationError("Đơn hàng không tồn tại.", 404)
    amount = Decimal(amount).quantize(Decimal("0.01"))
    paid = Decimal(order.paid_amount or 0)
    refunded = Decimal(order.refunded_amount or 0)
    if amount <= 0:
        raise PaymentOperationError("Số tiền hoàn phải lớn hơn 0.", 422)
    if amount > paid - refunded:
        raise PaymentOperationError("Số tiền hoàn vượt quá số tiền đã thanh toán.", 409)
    order.refunded_amount = refunded + amount
    order.payment_status = _payment_status(paid, Decimal(order.total_amount or 0), order.refunded_amount)
    fully_refunded = amount == paid - refunded and paid - refunded > 0
    returned_to_stock = False
    previous_status = order.status
    if fully_refunded and order.status in {"delivered", "completed"}:
        order_items = db.query(OrderItem).filter(
            OrderItem.order_id == order.id,
        ).order_by(OrderItem.id.asc()).all()
        product_ids = sorted({item.product_id for item in order_items})
        products = db.query(Product).filter(
            Product.business_id == business_id,
            Product.id.in_(product_ids),
        ).order_by(Product.id.asc()).with_for_update().all()
        product_map = {product.id: product for product in products}
        missing = [product_id for product_id in product_ids if product_id not in product_map]
        if missing:
            raise PaymentOperationError(
                f"Sản phẩm không tồn tại trong business: {missing}.",
                404,
            )
        for item in order_items:
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
                note="Hoàn tồn từ refund thanh toán",
            ))
        order.status = "refunded"
        returned_to_stock = True
    payment = OrderPayment(
        business_id=business_id,
        order_id=order.id,
        amount=amount,
        method="refund",
        status="refunded",
        reference=reason.strip() if reason else None,
        paid_at=datetime.now(timezone.utc).replace(tzinfo=None),
        refunded_amount=amount,
        idempotency_key=idempotency_key.strip(),
    )
    db.add(payment)
    db.flush()
    db.add(OrderEvent(
        business_id=business_id,
        order_type="sales_order",
        order_id=order.id,
        event_type="refund_created",
        actor_id=actor_id,
        metadata_={"payment_id": payment.id, "amount": str(amount)},
    ))
    if returned_to_stock:
        db.add(OrderEvent(
            business_id=business_id,
            order_type="sales_order",
            order_id=order.id,
            event_type="status_changed",
            from_status=previous_status,
            to_status="refunded",
            actor_id=actor_id,
            metadata_={"returned_to_stock": True},
        ))
    return payment, order, True


def record_purchase_payment(
    db: Session,
    *,
    purchase_order_id: int,
    amount: Decimal,
    method: str,
    status: str,
    reference: str | None,
    idempotency_key: str,
    actor_id: int | None,
    business_id: int,
) -> tuple[OrderPayment, PurchaseOrder, bool]:
    """Record payment against a supplier Purchase Order."""
    existing = _existing_payment(
        db,
        business_id=business_id,
        idempotency_key=idempotency_key,
        purchase_order_id=purchase_order_id,
    )
    if existing is not None:
        order = db.query(PurchaseOrder).filter(PurchaseOrder.id == purchase_order_id, PurchaseOrder.business_id == business_id).first()
        if order is None:
            raise PaymentOperationError("Purchase Order không tồn tại.", 404)
        return existing, order, False

    order = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == purchase_order_id,
        PurchaseOrder.business_id == business_id,
    ).with_for_update().first()
    if order is None:
        raise PaymentOperationError("Purchase Order không tồn tại.", 404)
    normalized_status = status.strip().lower()
    if normalized_status not in PAYMENT_STATUSES:
        raise PaymentOperationError("Trạng thái thanh toán không hợp lệ.", 422)
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if normalized_status == "paid":
        new_paid = Decimal(order.paid_amount or 0) + amount
        if new_paid > Decimal(order.total_spend or 0):
            raise PaymentOperationError("Số tiền thanh toán vượt quá giá trị Purchase Order.", 409)
        order.paid_amount = new_paid
        if new_paid <= 0:
            order.payment_status = "unpaid"
        elif new_paid >= Decimal(order.total_spend or 0):
            order.payment_status = "paid"
        else:
            order.payment_status = "partial"
    payment = OrderPayment(
        business_id=business_id,
        purchase_order_id=order.id,
        amount=amount,
        method=method.strip(),
        status=normalized_status,
        reference=reference.strip() if reference else None,
        paid_at=datetime.now(timezone.utc).replace(tzinfo=None) if normalized_status == "paid" else None,
        idempotency_key=idempotency_key.strip(),
    )
    db.add(payment)
    db.flush()
    db.add(OrderEvent(
        business_id=business_id,
        order_type="purchase_order",
        order_id=order.id,
        event_type="payment_created",
        actor_id=actor_id,
        metadata_={"payment_id": payment.id, "amount": str(amount), "method": payment.method, "status": normalized_status},
    ))
    return payment, order, True


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
    # Lock only the order row.  Combining ``FOR UPDATE`` with a joinedload
    # of the one-to-many items collection produces a LEFT OUTER JOIN, which
    # PostgreSQL rejects with "FOR UPDATE cannot be applied to the nullable
    # side of an outer join".  Load items in a separate query after the lock
    # so the inventory transition remains transactional without a 500.
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.business_id == business_id,
    ).with_for_update().first()
    if order is None:
        raise SalesOrderOperationError("Đơn hàng không tồn tại.", 404)

    order_items = db.query(OrderItem).filter(
        OrderItem.order_id == order.id,
    ).order_by(OrderItem.id.asc()).all()

    target = to_status.strip().lower()
    if target not in SALES_TRANSITIONS:
        raise SalesOrderOperationError("Trạng thái đơn hàng không hợp lệ.", 422)
    if target == "refunded":
        raise SalesOrderOperationError(
            "Dùng endpoint hoàn tiền để tạo giao dịch hoàn tiền trước khi đổi trạng thái đơn.",
            409,
        )
    allowed = SALES_TRANSITIONS.get(order.status, set())
    if target not in allowed:
        raise SalesOrderOperationError(f"Không thể chuyển {order.status} sang {target}.", 409)
    previous = order.status

    if target == "completed":
        net_paid = Decimal(order.paid_amount or 0) - Decimal(order.refunded_amount or 0)
        if net_paid < Decimal(order.total_amount or 0):
            raise SalesOrderOperationError("Chỉ có thể hoàn tất đơn khi đã thanh toán đủ.", 409)

    quantities_by_product = _quantities_by_product(order_items)

    product_ids = sorted({item.product_id for item in order_items})
    products = db.query(Product).filter(
        Product.business_id == business_id,
        Product.id.in_(product_ids),
    ).order_by(Product.id.asc()).with_for_update().all()
    product_map = {product.id: product for product in products}
    missing = [product_id for product_id in product_ids if product_id not in product_map]
    if missing:
        raise SalesOrderOperationError(f"Sản phẩm không tồn tại trong business: {missing}.", 404)

    if target == "confirmed":
        metadata = dict(order.metadata_ or {})
        reservation_held = (
            metadata.get("reservation_status") == "held"
            and int(order.reserved_quantity or 0) == sum(quantities_by_product.values())
        )
        if order.reservation_expires_at is not None and order.reservation_expires_at <= _now():
            reservation_held = False
            # A worker may not have run yet.  Release the stale hold before
            # checking availability so confirmation does not deadlock itself.
            for product_id, quantity in quantities_by_product.items():
                product = product_map[product_id]
                product.reserved_quantity = max(0, int(product.reserved_quantity or 0) - quantity)
            order.reserved_quantity = 0
            metadata["reservation_status"] = "expired"
            order.reservation_expires_at = None
        if not reservation_held:
            for product_id, quantity in quantities_by_product.items():
                product = product_map[product_id]
                stock = int(product.stock_quantity or 0)
                reserved = int(product.reserved_quantity or 0)
                available = stock - reserved
                if available < quantity:
                    raise SalesOrderOperationError(
                        f"Sản phẩm {product.sku} không đủ tồn khả dụng ({available}).",
                        409,
                    )
            total_reserved = 0
            for product_id, quantity in quantities_by_product.items():
                product = product_map[product_id]
                product.reserved_quantity = int(product.reserved_quantity or 0) + quantity
                total_reserved += quantity
            order.reserved_quantity = total_reserved
        metadata["reservation_status"] = "held"
        order.metadata_ = metadata

    elif target == "shipped":
        for product_id, quantity in quantities_by_product.items():
            product = product_map[product_id]
            stock = int(product.stock_quantity or 0)
            reserved = int(product.reserved_quantity or 0)
            if reserved < quantity or stock < quantity:
                raise SalesOrderOperationError(
                    f"Không thể xuất kho sản phẩm {product.sku}: tồn/giữ không đủ.",
                    409,
                )
        for product_id, quantity in quantities_by_product.items():
            product = product_map[product_id]
            before = int(product.stock_quantity or 0)
            product.stock_quantity = before - quantity
            product.reserved_quantity = int(product.reserved_quantity or 0) - quantity
            db.add(StockMovement(
                business_id=business_id,
                product_id=product.id,
                movement_type="sales_shipment",
                quantity=-quantity,
                quantity_before=before,
                quantity_after=product.stock_quantity,
                source_type="sales_order",
                source_id=order.id,
                actor_id=actor_id,
            ))
        order.reserved_quantity = 0

    elif target == "cancelled" and previous in {"draft", "confirmed", "processing"} and int(order.reserved_quantity or 0) > 0:
        for product_id, quantity in quantities_by_product.items():
            product = product_map[product_id]
            reserved = int(product.reserved_quantity or 0)
            if reserved < quantity:
                raise SalesOrderOperationError(
                    f"Không thể giải phóng tồn giữ cho sản phẩm {product.sku}.",
                    409,
                )
        for product_id, quantity in quantities_by_product.items():
            product = product_map[product_id]
            product.reserved_quantity = int(product.reserved_quantity or 0) - quantity
        order.reserved_quantity = 0
        order.reservation_expires_at = None
        metadata = dict(order.metadata_ or {})
        metadata["reservation_status"] = "cancelled"
        order.metadata_ = metadata

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
