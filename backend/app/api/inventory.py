"""Tenant-scoped inventory balance and ledger API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.inventory import StockMovement
from app.models.sales import Product
from app.schemas.inventory import InventoryBalanceOut, StockMovementListOut, StockMovementOut
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter()


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
        query = query.filter(StockMovement.product_id == product_id)
    if source_type:
        query = query.filter(StockMovement.source_type == source_type.strip())
    total = query.count()
    items = query.order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).offset(offset).limit(limit).all()
    return StockMovementListOut(items=items, total=total)
