import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.document import Document, DocumentChunk
from app.models.sales import Product
from app.rag.retriever import _retrieve_lexical


class CrmTwoShopEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            shop_a = Business(name="E2E Shop A", slug="e2e-shop-a")
            shop_b = Business(name="E2E Shop B", slug="e2e-shop-b")
            db.add_all([shop_a, shop_b])
            db.flush()

            customer_a = Customer(
                business_id=shop_a.id,
                channel="telegram",
                external_user_id="customer-a",
                name="Khách A",
            )
            customer_b = Customer(
                business_id=shop_b.id,
                channel="telegram",
                external_user_id="customer-b",
                name="Khách B",
            )
            product_a = Product(
                business_id=shop_a.id,
                sku="A-001",
                name="Sản phẩm A",
                price=100_000,
                stock_quantity=5,
            )
            product_b = Product(
                business_id=shop_b.id,
                sku="B-001",
                name="Sản phẩm B",
                price=900_000,
                stock_quantity=5,
            )
            db.add_all([customer_a, customer_b, product_a, product_b])
            db.flush()
            conversation_a = Conversation(
                business_id=shop_a.id,
                customer_id=customer_a.id,
                channel="telegram",
            )
            conversation_b = Conversation(
                business_id=shop_b.id,
                customer_id=customer_b.id,
                channel="telegram",
            )
            document_a = Document(
                business_id=shop_a.id,
                filename="shop-a.txt",
                file_type="txt",
                status="ready",
            )
            document_b = Document(
                business_id=shop_b.id,
                filename="shop-b.txt",
                file_type="txt",
                status="ready",
            )
            db.add_all([conversation_a, conversation_b, document_a, document_b])
            db.flush()
            db.add_all(
                [
                    DocumentChunk(
                        document_id=document_a.id,
                        content="Chính sách riêng của shop A cho phép đổi trong bảy ngày.",
                        chunk_index=0,
                    ),
                    DocumentChunk(
                        document_id=document_b.id,
                        content="Chính sách riêng của shop B cho phép đổi trong ba ngày.",
                        chunk_index=0,
                    ),
                ]
            )
            db.commit()
            cls.shop_a_id = shop_a.id
            cls.shop_b_id = shop_b.id
            cls.customer_a_id = customer_a.id
            cls.product_a_id = product_a.id
            cls.conversation_a_id = conversation_a.id
            cls.document_a_id = document_a.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()

    @classmethod
    def headers(cls, business_id):
        return {"X-Business-Id": str(business_id)}

    def test_two_shop_crm_commerce_reporting_and_rag_remain_isolated(self):
        created = self.client.post(
            "/api/orders",
            headers=self.headers(self.shop_a_id),
            json={
                "order_number": "E2E-A-001",
                "customer_id": self.customer_a_id,
                "conversation_id": self.conversation_a_id,
                "items": [{"product_id": self.product_a_id, "quantity": 1}],
            },
        )
        self.assertEqual(201, created.status_code, created.text)
        order = created.json()

        hidden = self.client.get(
            f"/api/orders/{order['id']}",
            headers=self.headers(self.shop_b_id),
        )
        self.assertEqual(404, hidden.status_code, hidden.text)

        for status in ("confirmed", "processing", "shipped", "delivered"):
            transitioned = self.client.post(
                f"/api/orders/{order['id']}/transition",
                headers=self.headers(self.shop_a_id),
                json={"to_status": status},
            )
            self.assertEqual(200, transitioned.status_code, transitioned.text)

        paid = self.client.post(
            f"/api/orders/{order['id']}/payments",
            headers=self.headers(self.shop_a_id),
            json={
                "idempotency_key": "e2e-payment-a-001",
                "amount": "100000",
                "method": "bank_transfer",
                "status": "paid",
            },
        )
        self.assertEqual(201, paid.status_code, paid.text)
        completed = self.client.post(
            f"/api/orders/{order['id']}/transition",
            headers=self.headers(self.shop_a_id),
            json={"to_status": "completed"},
        )
        self.assertEqual(200, completed.status_code, completed.text)

        report_a = self.client.get(
            "/api/reports/overview",
            headers=self.headers(self.shop_a_id),
        )
        report_b = self.client.get(
            "/api/reports/overview",
            headers=self.headers(self.shop_b_id),
        )
        self.assertEqual(1, report_a.json()["order_count"])
        self.assertEqual("100000.00", report_a.json()["total_revenue"])
        self.assertEqual(0, report_b.json()["order_count"])
        self.assertEqual("0.00", report_b.json()["total_revenue"])

        with Session(self.engine) as db:
            sources = _retrieve_lexical(
                "chính sách riêng đổi ngày",
                db,
                10,
                business_id=self.shop_a_id,
            )
        self.assertEqual([self.document_a_id], [source.document_id for source in sources])


if __name__ == "__main__":
    unittest.main()
