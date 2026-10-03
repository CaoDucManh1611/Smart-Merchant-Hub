import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database.bases import TenantBase

from app.db.dependencies import get_db
from app.tenancy.crm_session import get_tenant_db
from app.main import app
from app.models.business import Business
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.sales import Order, OrderItem, Product


class ProductOrderApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        TenantBase.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Sales One", slug="sales-one")
            two = Business(name="Sales Two", slug="sales-two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(
                business_id=one.id,
                channel="telegram",
                external_user_id="sales-customer",
                name="Buyer One",
            )
            other_customer = Customer(
                business_id=two.id,
                channel="facebook",
                external_user_id="sales-customer-b",
            )
            db.add_all([customer, other_customer])
            db.flush()
            conversation = Conversation(
                business_id=one.id,
                customer_id=customer.id,
                channel="telegram",
            )
            product = Product(
                business_id=one.id,
                sku="SERUM-01",
                name="Serum C",
                price=Decimal("420000"),
                stock_quantity=10,
            )
            other_product = Product(
                business_id=two.id,
                sku="OTHER-01",
                name="Other product",
                price=Decimal("100"),
                stock_quantity=10,
            )
            db.add_all([conversation, product, other_product])
            db.commit()
            cls.customer_id = customer.id
            cls.other_customer_id = other_customer.id
            cls.conversation_id = conversation.id
            cls.product_id = product.id
            cls.other_product_id = other_product.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        def override_get_tenant_db():
            with Session(cls.engine) as db:
                db.info["tenant_schema"] = "shop_test"
                yield db

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_tenant_db] = override_get_tenant_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_product_list_is_tenant_scoped(self):
        response = self.client.get("/api/products", headers={"X-Business-Id": "1"})
        self.assertEqual(200, response.status_code)
        product_ids = [item["id"] for item in response.json()["items"]]
        self.assertIn(self.product_id, product_ids)
        self.assertNotIn(self.other_product_id, product_ids)

    def test_product_url_crud_is_validated_and_tenant_scoped(self):
        created = self.client.post(
            "/api/products",
            headers={"X-Business-Id": "1"},
            json={"sku": "LINK-1", "name": "Linked item", "product_url": "https://shop.example/item/1"},
        )
        self.assertEqual(201, created.status_code, created.text)
        product_id = created.json()["id"]
        self.assertEqual("https://shop.example/item/1", created.json()["product_url"])

        read = self.client.get(f"/api/products/{product_id}", headers={"X-Business-Id": "1"})
        self.assertEqual("https://shop.example/item/1", read.json()["product_url"])
        self.assertEqual(404, self.client.get(f"/api/products/{product_id}", headers={"X-Business-Id": "2"}).status_code)

        updated = self.client.patch(
            f"/api/products/{product_id}",
            headers={"X-Business-Id": "1"},
            json={"product_url": "http://shop.example/new"},
        )
        self.assertEqual(200, updated.status_code, updated.text)
        self.assertEqual("http://shop.example/new", updated.json()["product_url"])
        self.assertEqual(422, self.client.patch(
            f"/api/products/{product_id}",
            headers={"X-Business-Id": "1"},
            json={"product_url": "javascript:alert(1)"},
        ).status_code)
        self.assertEqual(422, self.client.post(
            "/api/products",
            headers={"X-Business-Id": "1"},
            json={"sku": "LINK-BAD", "name": "Bad URL", "product_url": "https://user:password@shop.example"},
        ).status_code)

    def test_product_import_restocks_existing_sku_and_creates_new_sku(self):
        with Session(self.engine) as db:
            existing = Product(
                business_id=1,
                sku="IMPORT-EXISTING",
                name="Existing import product",
                price=Decimal("100000"),
                stock_quantity=10,
                status="active",
            )
            db.add(existing)
            db.commit()
            existing_id = existing.id

        content = (
            "Mã sản phẩm,Tên sản phẩm,Giá,Tồn kho,Trạng thái\n"
            "IMPORT-EXISTING,Existing import product,100000,5,Đang bán\n"
            "IMPORT-NEW,New import product,250000,7,Đang bán\n"
        ).encode("utf-8")
        response = self.client.post(
            "/api/products/import",
            headers={"X-Business-Id": "1"},
            files={"file": ("products.csv", content, "text/csv")},
        )
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(1, body["imported"])
        self.assertEqual(1, body["restocked"])
        self.assertEqual(5, body["restocked_quantity"])
        self.assertEqual(1, body["updated"])
        self.assertEqual(0, body["skipped"])

        with Session(self.engine) as db:
            self.assertEqual(15, db.get(Product, existing_id).stock_quantity)
            created = db.query(Product).filter(Product.business_id == 1, Product.sku == "IMPORT-NEW").one()
            self.assertEqual(7, created.stock_quantity)

    def test_product_import_duplicate_sku_is_a_preview_error_and_never_writes(self):
        content = b"sku,name,price,stock_quantity\nDUPLICATE-01,One,100,2\nDUPLICATE-01,One,100,3\n"
        preview = self.client.post(
            "/api/products/import?preview=true",
            headers={"X-Business-Id": "1"},
            files={"file": ("duplicates.csv", content, "text/csv")},
        )
        self.assertEqual(200, preview.status_code, preview.text)
        self.assertEqual(1, preview.json()["skipped"])
        self.assertIn("bị lặp", preview.json()["errors"][0])
        applied = self.client.post(
            "/api/products/import",
            headers={"X-Business-Id": "1"},
            files={"file": ("duplicates.csv", content, "text/csv")},
        )
        self.assertEqual(422, applied.status_code, applied.text)
        with Session(self.engine) as db:
            self.assertIsNone(db.query(Product).filter_by(business_id=1, sku="DUPLICATE-01").first())

    def test_product_import_saves_optional_product_url_and_rejects_unsafe_url(self):
        valid = self.client.post(
            "/api/products/import",
            headers={"X-Business-Id": "1"},
            files={"file": (
                "product-link.csv",
                "Mã sản phẩm,Tên sản phẩm,Giá,Tồn kho,Link sản phẩm\nLINK-IMPORT-01,Linked item,120000,2,https://shop.example/item/1\n".encode(),
                "text/csv",
            )},
        )
        self.assertEqual(200, valid.status_code, valid.text)
        with Session(self.engine) as db:
            product = db.query(Product).filter_by(business_id=1, sku="LINK-IMPORT-01").one()
            self.assertEqual("https://shop.example/item/1", product.product_url)

        invalid = self.client.post(
            "/api/products/import?preview=true",
            headers={"X-Business-Id": "1"},
            files={"file": (
                "unsafe-product-link.csv",
                b"sku,name,price,stock_quantity,product_url\nLINK-IMPORT-BAD,Unsafe item,120000,2,javascript:alert(1)\n",
                "text/csv",
            )},
        )
        self.assertEqual(200, invalid.status_code, invalid.text)
        self.assertEqual(1, invalid.json()["skipped"])
        self.assertIn("link sản phẩm không hợp lệ", invalid.json()["errors"][0])

    def test_product_inventory_export_is_tenant_scoped_and_not_a_receipt_template(self):
        response = self.client.get("/api/products/export.csv", headers={"X-Business-Id": "1"})
        self.assertEqual(200, response.status_code)
        csv_text = response.content.decode("utf-8-sig")
        self.assertIn("sku_snapshot", csv_text.splitlines()[0])
        self.assertIn("SERUM-01", csv_text)
        self.assertNotIn("OTHER-01", csv_text)
        replay = self.client.post(
            "/api/products/import",
            headers={"X-Business-Id": "1"},
            files={"file": ("export.csv", response.content, "text/csv")},
        )
        self.assertEqual(400, replay.status_code)

    def test_order_import_preview_is_tenant_scoped_atomic_and_idempotent(self):
        content = (
            f"order_number;customer_id;sku;quantity;conversation_id\n"
            f"CSV-IMPORT-01;{self.customer_id};SERUM-01;1;{self.conversation_id}\n"
            f"CSV-IMPORT-01;{self.customer_id};SERUM-01;2;{self.conversation_id}\n"
        ).encode()
        def upload(suffix):
            return self.client.post(
                f"/api/orders/import{suffix}",
                headers={"X-Business-Id": "1"},
                files={"file": ("orders.csv", content, "text/csv")},
            )

        preview = upload("?preview=true")
        self.assertEqual(200, preview.status_code, preview.text)
        self.assertEqual(1, preview.json()["orders"])
        self.assertEqual(1260000, float(preview.json()["total_amount"]))
        self.assertEqual("CSV-IMPORT-01", preview.json()["orders_preview"][0]["order_number"])
        with Session(self.engine) as db:
            self.assertIsNone(db.query(Order).filter_by(business_id=1, order_number="CSV-IMPORT-01").first())

        imported = upload("")
        self.assertEqual(1, imported.json()["imported"])
        replay = upload("")
        self.assertTrue(replay.json()["already_imported"])
        with Session(self.engine) as db:
            order = db.query(Order).filter_by(business_id=1, order_number="CSV-IMPORT-01").one()
            item = db.query(OrderItem).filter_by(order_id=order.id).one()
            self.assertEqual("draft", order.status)
            self.assertEqual(3, item.quantity)
            self.assertEqual(10, db.get(Product, self.product_id).stock_quantity)

    def test_order_import_preview_reports_cross_tenant_rows_before_any_write(self):
        content = f"order_number,customer_id,sku,quantity\nCSV-FOREIGN-01,{self.other_customer_id},SERUM-01,1\n".encode()
        preview = self.client.post(
            "/api/orders/import?preview=true",
            headers={"X-Business-Id": "1"},
            files={"file": ("foreign.csv", content, "text/csv")},
        )
        self.assertEqual(200, preview.status_code, preview.text)
        self.assertTrue(any("khách hàng" in error for error in preview.json()["errors"]))
        applied = self.client.post(
            "/api/orders/import",
            headers={"X-Business-Id": "1"},
            files={"file": ("foreign.csv", content, "text/csv")},
        )
        self.assertEqual(422, applied.status_code)
        with Session(self.engine) as db:
            self.assertIsNone(db.query(Order).filter_by(business_id=1, order_number="CSV-FOREIGN-01").first())

    def test_product_import_saves_english_display_name_without_changing_canonical_name(self):
        content = (
            "sku,name,name_en,price,stock_quantity\n"
            "HOME-EN-01,Điện gia dụng mẫu 01,Household appliance model 01,349000,230\n"
        ).encode("utf-8")
        response = self.client.post(
            "/api/products/import",
            headers={"X-Business-Id": "1"},
            files={"file": ("products.csv", content, "text/csv")},
        )
        self.assertEqual(200, response.status_code, response.text)
        with Session(self.engine) as db:
            product = db.query(Product).filter_by(business_id=1, sku="HOME-EN-01").one()
            self.assertEqual("Điện gia dụng mẫu 01", product.name)
            self.assertEqual("Household appliance model 01", product.metadata_["display_names"]["en"])

    def test_product_import_preview_and_replay_do_not_double_stock(self):
        content = b"sku,name,price,stock_quantity\nIDEMPOTENT-01,Fixture product,10000,5\n"
        def upload(suffix=""):
            return self.client.post(
                f"/api/products/import{suffix}",
                headers={"X-Business-Id": "1"},
                files={"file": ("receipt.csv", content, "text/csv")},
            )

        preview = upload("?preview=true")
        self.assertEqual(200, preview.status_code, preview.text)
        self.assertTrue(preview.json()["preview"])
        with Session(self.engine) as db:
            self.assertIsNone(db.query(Product).filter_by(sku="IDEMPOTENT-01").first())
        first = upload()
        self.assertEqual(200, first.status_code, first.text)
        repeated = upload()
        self.assertEqual(200, repeated.status_code, repeated.text)
        self.assertTrue(repeated.json()["already_imported"])
        with Session(self.engine) as db:
            self.assertEqual(5, db.query(Product).filter_by(sku="IDEMPOTENT-01").one().stock_quantity)
        explicit = upload("?allow_repeat=true")
        self.assertEqual(200, explicit.status_code, explicit.text)
        with Session(self.engine) as db:
            self.assertEqual(10, db.query(Product).filter_by(sku="IDEMPOTENT-01").one().stock_quantity)

    def test_product_import_rejects_partial_file_without_writing_valid_rows(self):
        content = (
            "sku,name,price,stock_quantity\n"
            "VALID-ATOMIC-01,Valid,10000,1\n"
            "BROKEN-ATOMIC-01,Broken,not-a-price,1\n"
        ).encode()
        response = self.client.post(
            "/api/products/import",
            headers={"X-Business-Id": "1"},
            files={"file": ("broken.csv", content, "text/csv")},
        )
        self.assertEqual(422, response.status_code, response.text)
        with Session(self.engine) as db:
            self.assertIsNone(db.query(Product).filter_by(sku="VALID-ATOMIC-01").first())

    def test_order_uses_database_product_price_and_calculates_total(self):
        response = self.client.post(
            "/api/orders",
            headers={"X-Business-Id": "1"},
            json={
                "order_number": "ORD-001",
                "customer_id": self.customer_id,
                "conversation_id": self.conversation_id,
                "items": [{"product_id": self.product_id, "quantity": 2}],
            },
        )
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertEqual("840000.00", body["total_amount"])
        self.assertEqual(1, len(body["items"]))
        self.assertEqual("420000.00", body["items"][0]["unit_price"])

    def test_order_number_is_generated_when_omitted(self):
        response = self.client.post(
            "/api/orders",
            headers={"X-Business-Id": "1"},
            json={
                "customer_id": self.customer_id,
                "items": [{"product_id": self.product_id, "quantity": 1}],
            },
        )
        self.assertEqual(201, response.status_code)
        self.assertRegex(response.json()["order_number"], r"^ORD-\d{14}(?:-\d+)?$")

    def test_order_cannot_reference_other_tenant_product(self):
        response = self.client.post(
            "/api/orders",
            headers={"X-Business-Id": "1"},
            json={
                "order_number": "ORD-CROSS-TENANT",
                "customer_id": self.customer_id,
                "items": [{"product_id": self.other_product_id, "quantity": 1}],
            },
        )
        self.assertEqual(404, response.status_code)

    def test_order_cannot_reference_other_tenant_customer(self):
        response = self.client.post(
            "/api/orders",
            headers={"X-Business-Id": "1"},
            json={
                "order_number": "ORD-CROSS-CUSTOMER",
                "customer_id": self.other_customer_id,
                "items": [{"product_id": self.product_id, "quantity": 1}],
            },
        )
        self.assertEqual(404, response.status_code)

    def test_order_must_start_as_draft(self):
        response = self.client.post(
            "/api/orders",
            headers={"X-Business-Id": "1"},
            json={
                "order_number": "ORD-NON-DRAFT",
                "customer_id": self.customer_id,
                "items": [{"product_id": self.product_id, "quantity": 1}],
                "status": "confirmed",
            },
        )
        self.assertEqual(422, response.status_code, response.text)

    def test_stock_adjustment_is_ledgered_and_product_patch_cannot_bypass_it(self):
        bypass = self.client.patch(
            f"/api/products/{self.product_id}",
            headers={"X-Business-Id": "1"},
            json={"stock_quantity": 20},
        )
        self.assertEqual(409, bypass.status_code, bypass.text)

        adjustment = self.client.post(
            f"/api/inventory/products/{self.product_id}/adjustments",
            headers={"X-Business-Id": "1"},
            json={"quantity": 2, "note": "Kiểm kho"},
        )
        self.assertEqual(201, adjustment.status_code, adjustment.text)
        self.assertEqual(12, adjustment.json()["balance"]["stock_quantity"])

        movements = self.client.get(
            f"/api/inventory/movements?product_id={self.product_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(1, movements.json()["total"])
        self.assertEqual("inventory_adjustment", movements.json()["items"][0]["movement_type"])
        self.assertEqual(2, movements.json()["items"][0]["quantity"])

        zero_adjustment = self.client.post(
            f"/api/inventory/products/{self.product_id}/adjustments",
            headers={"X-Business-Id": "1"},
            json={"quantity": 0},
        )
        self.assertEqual(422, zero_adjustment.status_code, zero_adjustment.text)

    def test_product_creation_records_opening_stock_in_inventory_ledger(self):
        created = self.client.post(
            "/api/products",
            headers={"X-Business-Id": "1"},
            json={
                "sku": "OPENING-STOCK",
                "name": "Opening stock product",
                "price": "10",
                "stock_quantity": 3,
            },
        )
        self.assertEqual(201, created.status_code, created.text)
        product_id = created.json()["id"]

        movements = self.client.get(
            f"/api/inventory/movements?product_id={product_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(1, movements.json()["total"])
        movement = movements.json()["items"][0]
        self.assertEqual("opening_balance", movement["movement_type"])
        self.assertEqual(3, movement["quantity"])
        self.assertEqual(0, movement["quantity_before"])
        self.assertEqual(3, movement["quantity_after"])

    def test_inventory_movements_rejects_a_product_from_another_tenant(self):
        response = self.client.get(
            f"/api/inventory/movements?product_id={self.other_product_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(404, response.status_code, response.text)

    def test_revenue_report_is_grouped_by_conversation_channel_and_tenant_scoped(self):
        existing = self.client.get(
            "/api/orders",
            headers={"X-Business-Id": "1"},
        )
        report_order = next((item for item in existing.json()["items"] if item.get("conversation_id") == self.conversation_id), None)
        if report_order is None:
            create = self.client.post(
                "/api/orders",
                headers={"X-Business-Id": "1"},
                json={
                    "order_number": "ORD-REPORT",
                    "customer_id": self.customer_id,
                    "conversation_id": self.conversation_id,
                    "items": [{"product_id": self.product_id, "quantity": 2}],
                },
            )
            self.assertEqual(201, create.status_code)
            report_order = create.json()
        if report_order["status"] == "draft":
            confirmed = self.client.post(
                f"/api/orders/{report_order['id']}/transition",
                headers={"X-Business-Id": "1"},
                json={"to_status": "confirmed"},
            )
            self.assertEqual(200, confirmed.status_code, confirmed.text)
        response = self.client.get(
            "/api/reports/revenue-by-channel",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, response.status_code)
        body = response.json()
        telegram = next(item for item in body["items"] if item["channel"] == "telegram")
        self.assertGreaterEqual(float(body["total_revenue"]), 840000)
        self.assertGreaterEqual(telegram["order_count"], 1)
        self.assertGreaterEqual(float(telegram["revenue"]), 840000)

        other_tenant = self.client.get(
            "/api/reports/revenue-by-channel",
            headers={"X-Business-Id": "2"},
        )
        self.assertEqual(200, other_tenant.status_code)
        self.assertEqual([], other_tenant.json()["items"])
        self.assertEqual(0, float(other_tenant.json()["total_revenue"]))

    def test_revenue_by_channel_excludes_shopee(self):
        with Session(self.engine) as db:
            shopee = Conversation(business_id=1, customer_id=self.customer_id, channel="shopee")
            db.add(shopee)
            db.flush()
            db.add(Order(
                business_id=1, customer_id=self.customer_id, conversation_id=shopee.id,
                order_number="ORD-SHOPEE-EXCLUDED", status="paid", total_amount=Decimal("999999"),
            ))
            db.commit()
        response = self.client.get("/api/reports/revenue-by-channel", headers={"X-Business-Id": "1"})
        self.assertEqual(200, response.status_code, response.text)
        self.assertNotIn("shopee", {item["channel"].lower() for item in response.json()["items"]})


if __name__ == "__main__":
    unittest.main()
