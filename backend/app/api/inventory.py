"""Tenant-scoped inventory balance and ledger API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_write_access
from app.db.dependencies import get_db
from app.models.business import User
from app.models.inventory import StockMovement
from app.models.sales import Product
from app.schemas.inventory import (
    InventoryAdjustmentOut,
    InventoryBalanceOut,
    StockAdjustmentCreate,
    StockMovementListOut,
    StockMovementOut,
)
from app.services.audit_service import record_audit
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter()


def _balance(product: Product) -> InventoryBalanceOut:
    stock = int(product.stock_quantity or 0)
    reserved = int(product.reserved_quantity or 0)
    if stock < 0 or reserved < 0 or reserved > stock:
        raise HTTPException(status_code=409, detail="Dữ liệu tồn kho không hợp lệ.")
    return InventoryBalanceOut(
        product_id=product.id,
        stock_quantity=stock,
        reserved_quantity=reserved,
        available_quantity=stock - reserved,
    )


@router.get("/inventory/products/{product_id}", response_model=InventoryBalanceOut)
def get_inventory_balance(
    product_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.business_id == tenant.business_id,
    ).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại.")
    return _balance(product)


@router.post(
    "/inventory/products/{product_id}/adjustments",
    response_model=InventoryAdjustmentOut,
    status_code=201,
    dependencies=[Depends(require_write_access)],
)
def adjust_inventory(
    product_id: int,
    payload: StockAdjustmentCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    if payload.quantity == 0:
        raise HTTPException(status_code=422, detail="Số lượng điều chỉnh phải khác 0.")
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.business_id == tenant.business_id,
    ).with_for_update().first()
    if product is None:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại.")
    before = int(product.stock_quantity or 0)
    reserved = int(product.reserved_quantity or 0)
    after = before + payload.quantity
    if before < 0 or reserved < 0 or after < reserved:
        raise HTTPException(status_code=409, detail="Điều chỉnh làm tồn khả dụng bị âm.")
    product.stock_quantity = after
    note = payload.effective_note
    movement = StockMovement(
        business_id=tenant.business_id,
        product_id=product.id,
        movement_type="inventory_adjustment",
        quantity=payload.quantity,
        quantity_before=before,
        quantity_after=after,
        source_type="manual_adjustment",
        source_id=product.id,
        actor_id=actor.id if actor else None,
        note=note,
    )
    db.add(movement)
    db.flush()
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="adjust",
        resource_type="inventory",
        resource_id=str(product.id),
        metadata={"quantity": payload.quantity, "reason": note, "movement_id": movement.id},
    )
    db.commit()
    db.refresh(movement)
    return InventoryAdjustmentOut(movement=movement, balance=_balance(product))


@router.get("/inventory/movements", response_model=StockMovementListOut)
def list_inventory_movements(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    product_id: int | None = Query(default=None, ge=1),
    source_type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(StockMovement).filter(StockMovement.business_id == tenant.business_id)
    if product_id is not None:
        product = db.query(Product).filter(
            Product.id == product_id,
            Product.business_id == tenant.business_id,
        ).first()
        if product is None:
            raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại.")
        query = query.filter(StockMovement.product_id == product_id)
    if source_type:
        query = query.filter(StockMovement.source_type == source_type.strip())
    total = query.count()
    items = query.order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).offset(offset).limit(limit).all()
    return StockMovementListOut(items=items, total=total)
