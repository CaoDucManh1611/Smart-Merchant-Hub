"""Transactional inventory operations for purchase receiving."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.models.inventory import PurchaseReceipt, PurchaseReceiptItem, StockMovement
from app.models.order_event import OrderEvent
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.sales import Product


class InventoryOperationError(ValueError):
    """A controlled validation error at the inventory boundary."""

    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def receive_purchase_order(
    db: Session,
    *,
    purchase_order_id: int,
    lines: Sequence[tuple[int, int]],
    actor_id: int | None,
    business_id: int,
    idempotency_key: str,
    note: str | None = None,
) -> tuple[PurchaseReceipt, bool]:
    """Receive PO quantities and increase stock in one transaction.

    The caller owns the transaction boundary and must commit once the returned
    receipt is serialized successfully. Existing idempotency keys return the
    original receipt without changing stock.
    """
    key = idempotency_key.strip()
    if not key:
        raise InventoryOperationError("idempotency_key là bắt buộc.", 422)
    if not lines:
        raise InventoryOperationError("Cần ít nhất một dòng nhận hàng.", 422)

    existing = db.query(PurchaseReceipt).filter(
        PurchaseReceipt.business_id == business_id,
        PurchaseReceipt.idempotency_key == key,
    ).first()
    if existing is not None:
        return existing, False

    order = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == purchase_order_id,
        PurchaseOrder.business_id == business_id,
    ).with_for_update().first()
    if order is None:
        raise InventoryOperationError("Purchase Order không tồn tại.", 404)
    if order.status not in {"submitted", "partially_received"}:
        raise InventoryOperationError(
            f"Không thể nhận hàng khi PO đang ở trạng thái {order.status}.",
            409,
        )
    from_status = order.status

    normalized_lines = [(int(item_id), int(quantity)) for item_id, quantity in lines]
    item_ids = [item_id for item_id, _ in normalized_lines]
    if len(item_ids) != len(set(item_ids)):
        raise InventoryOperationError("Không được lặp dòng sản phẩm trong một receipt.", 422)
    if any(quantity <= 0 for _, quantity in normalized_lines):
        raise InventoryOperationError("Số lượng nhận phải lớn hơn 0.", 422)

    po_items = db.query(PurchaseOrderItem).filter(
        PurchaseOrderItem.purchase_order_id == order.id,
        PurchaseOrderItem.id.in_(item_ids),
    ).with_for_update().all()
    item_map = {item.id: item for item in po_items}
    missing = [item_id for item_id in item_ids if item_id not in item_map]
    if missing:
        raise InventoryOperationError(f"Dòng PO không tồn tại: {missing}.", 404)

    product_ids = sorted({item_map[item_id].product_id for item_id in item_ids})
    products = db.query(Product).filter(
        Product.business_id == business_id,
        Product.id.in_(product_ids),
    ).with_for_update().all()
    product_map = {product.id: product for product in products}
    missing_products = [product_id for product_id in product_ids if product_id not in product_map]
    if missing_products:
        raise InventoryOperationError(f"Sản phẩm không tồn tại trong business: {missing_products}.", 404)

    receipt = PurchaseReceipt(
        business_id=business_id,
        purchase_order_id=order.id,
        received_by=actor_id,
        note=note,
        idempotency_key=key,
    )
    db.add(receipt)
    db.flush()

    movement_metadata: list[dict[str, int]] = []
    for item_id, quantity in normalized_lines:
        item = item_map[item_id]
        received = int(item.received_quantity or 0)
        if received + quantity > item.quantity:
            raise InventoryOperationError(
                f"Dòng {item.id} nhận vượt số lượng đặt ({item.quantity}).",
                409,
            )
        product = product_map[item.product_id]
        before = int(product.stock_quantity or 0)
        after = before + quantity
        if after < 0:
            raise InventoryOperationError("Tồn kho không được âm.", 409)
        item.received_quantity = received + quantity
        product.stock_quantity = after
        db.add(PurchaseReceiptItem(
            receipt_id=receipt.id,
            purchase_order_item_id=item.id,
            quantity=quantity,
        ))
        db.add(StockMovement(
            business_id=business_id,
            product_id=product.id,
            movement_type="purchase_receipt",
            quantity=quantity,
            quantity_before=before,
            quantity_after=after,
            source_type="purchase_receipt",
            source_id=receipt.id,
            actor_id=actor_id,
            note=note,
        ))
        movement_metadata.append({"purchase_order_item_id": item.id, "quantity": quantity})

    all_received = all(
        int(item.received_quantity or 0) >= int(item.quantity)
        for item in order.items
    )
    order.status = "received" if all_received else "partially_received"
    db.add(OrderEvent(
        business_id=business_id,
        order_type="purchase_order",
        order_id=order.id,
        event_type="receipt_created",
        from_status=from_status,
        to_status=order.status,
        actor_id=actor_id,
        metadata_={"receipt_id": receipt.id, "items": movement_metadata},
    ))
    return receipt, True
