import unittest

from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register current metadata
from app.database.session import Base


class P102SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(cls.engine)

    def test_new_business_tables_and_columns_exist(self):
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        self.assertTrue(
            {
                "suppliers",
                "stock_movements",
                "purchase_receipts",
                "purchase_receipt_items",
                "order_payments",
                "order_events",
            }.issubset(tables)
        )
        product_columns = {column["name"] for column in inspector.get_columns("products")}
        order_columns = {column["name"] for column in inspector.get_columns("orders")}
        purchase_columns = {column["name"] for column in inspector.get_columns("purchase_orders")}
        purchase_item_columns = {column["name"] for column in inspector.get_columns("purchase_order_items")}
        self.assertIn("reserved_quantity", product_columns)
        self.assertIn("payment_status", order_columns)
        self.assertIn("supplier_id", purchase_columns)
        self.assertIn("received_quantity", purchase_item_columns)

    def test_idempotency_keys_are_unique_per_business(self):
        inspector = inspect(self.engine)
        for table in ("purchase_receipts", "order_payments"):
            self.assertIn(table, inspector.get_table_names())
            unique_constraints = inspector.get_unique_constraints(table)
            unique_columns = {tuple(item["column_names"]) for item in unique_constraints}
            self.assertIn(("business_id", "idempotency_key"), unique_columns)


if __name__ == "__main__":
    unittest.main()
