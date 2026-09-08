import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business
from app.models.sales import Product
from app.services.product_catalog_service import (
    extract_catalog_products,
    sync_catalog_products,
)


CATALOG_TEXT = """
- Serum Vitamin C Lunari (SKU SERUM-01): giá 420.000 đồng/chai 30 ml. Tồn kho thử nghiệm: 10 sản phẩm.
- Combo chăm sóc da cơ bản (SKU COMBO-01): gồm sữa rửa mặt và serum. Giá niêm yết 888.000 đồng; giá combo 799.000 đồng. Tồn kho combo thử nghiệm: 6 bộ.
"""


class ProductCatalogServiceTests(unittest.TestCase):
    def test_extracts_structured_products_and_combo_price(self):
        records = extract_catalog_products(CATALOG_TEXT)

        self.assertEqual(["SERUM-01", "COMBO-01"], [item.sku for item in records])
        self.assertEqual("Serum Vitamin C Lunari", records[0].name)
        self.assertEqual(Decimal("420000"), records[0].price)
        self.assertEqual(10, records[0].stock_quantity)
        self.assertEqual(Decimal("799000"), records[1].price)
        self.assertEqual(6, records[1].stock_quantity)
        self.assertIn("combo cơ bản", records[1].aliases)

    def test_syncs_catalog_products_into_tenant_product_table(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(engine)
        with Session(engine) as db:
            business = Business(name="Catalog Shop", slug="catalog-shop")
            db.add(business)
            db.flush()

            created = sync_catalog_products(
                db,
                business_id=business.id,
                source_document_id=17,
                text=CATALOG_TEXT,
            )
            db.commit()

            combo = db.query(Product).filter_by(sku="COMBO-01").one()
            self.assertEqual(2, len(created))
            self.assertEqual("Combo chăm sóc da cơ bản", combo.name)
            self.assertEqual(Decimal("799000.00"), combo.price)
            self.assertEqual(6, combo.stock_quantity)
            self.assertEqual(17, combo.metadata_["catalog_source_document_id"])
            self.assertIn("bộ chăm sóc da cơ bản", combo.metadata_["aliases"])


if __name__ == "__main__":
    unittest.main()
