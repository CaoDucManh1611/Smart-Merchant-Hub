import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business
from app.models.message import Message
from app.models.sales import Product
from app.services.product_resolver import resolve_product, resolve_product_mentions


class ProductResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Resolver Shop", slug="resolver-shop")
            db.add(business)
            db.flush()
            db.add(Product(
                business_id=business.id,
                sku="COMBO-01",
                name="Combo chăm sóc da cơ bản",
                price=Decimal("799000"),
                stock_quantity=6,
                metadata_={"aliases": ["combo cơ bản", "bộ chăm sóc da cơ bản"]},
                status="active",
            ))
            db.commit()
            cls.business_id = business.id

    def test_resolves_alias_without_exact_canonical_name(self):
        with Session(self.engine) as db:
            product = resolve_product(
                db,
                business_id=self.business_id,
                text="giá của 6 bộ combo cơ bản hết bao nhiêu",
            )

            self.assertIsNotNone(product)
            self.assertEqual("COMBO-01", product.sku)

    def test_resolves_accentless_product_text(self):
        with Session(self.engine) as db:
            product = resolve_product(
                db,
                business_id=self.business_id,
                text="bo cham soc da co ban",
            )

            self.assertIsNotNone(product)
            self.assertEqual("Combo chăm sóc da cơ bản", product.name)

    def test_resolves_short_follow_up_from_previous_customer_message(self):
        with Session(self.engine) as db:
            db.add(Message(
                conversation_id=71,
                channel="instagram",
                direction="inbound",
                content="Bạn có bao nhiêu combo chăm sóc da cơ bản?",
            ))
            db.commit()

            product = resolve_product(
                db,
                business_id=self.business_id,
                conversation_id=71,
                text="giá của 6 bộ đó hết bao nhiêu",
            )

            self.assertIsNotNone(product)
            self.assertEqual("COMBO-01", product.sku)

    def test_quantity_number_does_not_override_an_explicit_numbered_product_name(self):
        with Session(self.engine) as db:
            appliance = Product(
                business_id=self.business_id,
                sku="HOME-01",
                name="Điện gia dụng mẫu 01",
                price=Decimal("349000"),
                stock_quantity=230,
                status="active",
            )
            db.add_all([
                appliance,
                Product(
                    business_id=self.business_id,
                    sku="FASHION-20",
                    name="Thời trang mẫu 20",
                    price=Decimal("289000"),
                    stock_quantity=100,
                    status="active",
                ),
            ])
            db.flush()

            products = resolve_product_mentions(
                db,
                business_id=self.business_id,
                text="tôi muốn mua 20 cái điện gia dụng mẫu 01",
            )

            self.assertEqual([appliance.id], [product.id for product in products])

    def test_exact_product_name_beats_weak_keyword_match_in_english_query(self):
        with Session(self.engine) as db:
            appliance = Product(
                business_id=self.business_id,
                sku="HOME-01",
                name="Điện gia dụng mẫu 01",
                price=Decimal("349000"),
                stock_quantity=230,
                status="active",
            )
            unrelated = Product(
                business_id=self.business_id,
                sku="SPORT-01",
                name="Thể thao mẫu 01",
                price=Decimal("89000"),
                stock_quantity=450,
                metadata_={"keywords": ["how much"]},
                status="active",
            )
            db.add_all([appliance, unrelated])
            db.flush()

            products = resolve_product_mentions(
                db,
                business_id=self.business_id,
                text="How much would it cost to buy 10 units of the Điện gia dụng mẫu 01?",
            )

            self.assertEqual([appliance.id], [product.id for product in products])
            db.delete(appliance)
            db.delete(unrelated)
            db.commit()


if __name__ == "__main__":
    unittest.main()
