"""Contract tests for schema-local commerce operations."""

from pathlib import Path

from app.database.bases import TenantBase
from app.models.inventory import StockMovement
from app.models.sales import Order, Product
from app.models.supplier import Supplier


ROOT = Path(__file__).resolve().parents[1]


def test_commerce_models_are_tenant_metadata_without_platform_foreign_keys():
    assert {Product, Order, StockMovement, Supplier}.issubset(
        set(TenantBase.registry.mappers and [mapper.class_ for mapper in TenantBase.registry.mappers])
    )
    for model in (Product, Order, StockMovement, Supplier):
        assert all(
            (foreign_key.target_fullname.split(".", 1)[0] not in {"businesses", "users"})
            for column in model.__table__.columns
            for foreign_key in column.foreign_keys
        )


def test_commerce_apis_use_tenant_session_dependency():
    for name in ("sales.py", "inventory.py", "suppliers.py", "purchase_orders.py"):
        source = (ROOT / "app" / "api" / name).read_text(encoding="utf-8")
        assert "get_tenant_db" in source
        assert "Depends(get_db)" not in source

