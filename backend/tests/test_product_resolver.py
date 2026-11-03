import unittest
from decimal import Decimal
from unittest.mock import Mock
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.message import Message
from app.models.sales import Product
from app.services.customer_collection_flow import _start_product_quote
from app.services.product_resolver import (
    find_explicit_product_mentions,
    resolve_product,
    resolve_product_mentions,
)


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
            customer = Customer(
                business_id=business.id,
                channel="instagram",
                external_user_id="resolver-user",
            )
            db.add(customer)
            db.flush()
            conversation = Conversation(
                business_id=business.id,
                customer_id=customer.id,
                channel="instagram",
            )
            db.add(conversation)
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
            cls.conversation_id = conversation.id

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
                conversation_id=self.conversation_id,
                channel="instagram",
                direction="inbound",
                content="Bạn có bao nhiêu combo chăm sóc da cơ bản?",
            ))
            db.commit()

            product = resolve_product(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                text="giá của 6 bộ đó hết bao nhiêu",
            )

            self.assertIsNotNone(product)
            self.assertEqual("COMBO-01", product.sku)

    def test_resolves_follow_up_from_one_exact_product_in_latest_bot_reply(self):
        with Session(self.engine) as db:
            db.query(Message).filter(Message.conversation_id == self.conversation_id).delete()
            db.add_all([
                Message(
                    conversation_id=self.conversation_id,
                    channel="instagram",
                    direction="inbound",
                    sender_type="customer",
                    content="Bạn có combo chăm sóc da cơ bản không?",
                ),
                Message(
                    conversation_id=self.conversation_id,
                    channel="instagram",
                    direction="outbound",
                    sender_type="bot",
                    content="Combo chăm sóc da cơ bản có giá 799.000 đồng.",
                ),
            ])
            db.commit()

            product = resolve_product(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                text="Cái đó còn hàng không?",
            )

            self.assertIsNotNone(product)
            self.assertEqual("COMBO-01", product.sku)
            db.query(Message).filter(Message.conversation_id == self.conversation_id).delete()
            db.commit()

    def test_does_not_guess_between_products_in_latest_bot_reply(self):
        with Session(self.engine) as db:
            db.query(Message).filter(Message.conversation_id == self.conversation_id).delete()
            db.query(Product).filter(
                Product.business_id == self.business_id,
                Product.sku == "HOME-01",
            ).delete()
            db.add(Product(
                business_id=self.business_id,
                sku="HOME-01",
                name="Điện gia dụng mẫu 01",
                price=Decimal("349000"),
                stock_quantity=4,
                status="active",
            ))
            db.add(Message(
                conversation_id=self.conversation_id,
                channel="instagram",
                direction="outbound",
                sender_type="bot",
                content="Combo chăm sóc da cơ bản hoặc Điện gia dụng mẫu 01 đều có thể phù hợp.",
            ))
            db.commit()

            product = resolve_product(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                text="Cái đó còn hàng không?",
            )

            self.assertIsNone(product)
            db.query(Message).filter(Message.conversation_id == self.conversation_id).delete()
            db.query(Product).filter(
                Product.business_id == self.business_id,
                Product.sku == "HOME-01",
            ).delete()
            db.commit()

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


class DemoProductResolverRegressionTests(unittest.TestCase):
    def test_tire_size_comparison_matches_each_requested_dimension(self):
        products = [
            SimpleNamespace(id=1, sku="TIRE-7090", name="Lop xe so 70/90-17 khong sam", metadata_={}),
            SimpleNamespace(id=2, sku="TIRE-8090", name="Lop xe so 80/90-17 khong sam", metadata_={}),
            SimpleNamespace(id=3, sku="TIRE-90100", name="Lop xe so 90/100-17 khong sam", metadata_={}),
        ]
        matches = find_explicit_product_mentions(
            products, "Shop co lop 70/90-17 va 80/90-17 khong? So sanh gia giup toi."
        )
        self.assertEqual([1, 2], [product.id for product in matches])

    def test_exact_demo_name_beats_earlier_weak_quantity_match(self):
        bottle = Product(
            id=53, business_id=4, sku="BOTTLE-600",
            name="[DEMO] Bình giữ nhiệt inox 600 ml Mây Nhà",
            price=Decimal("189000"), stock_quantity=38, status="active",
        )
        hooks = Product(
            id=76, business_id=4, sku="HOOKS-10",
            name="[DEMO] Bộ móc treo chống trượt 10 chiếc Mây Nhà",
            price=Decimal("99000"), stock_quantity=20, status="active",
        )
        db = Mock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [bottle, hooks]

        products = resolve_product_mentions(
            db,
            business_id=4,
            text="Nếu mua 2 chiếc bình giữ nhiệt inox 600 ml Mây Nhà thì tổng bao nhiêu? Mình chưa xác nhận đặt hàng nhé.",
        )

        self.assertEqual([bottle.id], [product.id for product in products])

        answer = _start_product_quote(
            db, business_id=4, customer_id=1, conversation_id=None,
            source_channel="shopee",
            text="Cho mình hỏi 2 chiếc bình giữ nhiệt inox 600 ml Mây Nhà tổng bao nhiêu tiền? Mình chỉ hỏi giá, chưa đặt hàng.",
        )
        self.assertEqual("catalog_answer", answer.status)
        self.assertIn("378.000 đồng", answer.prompt)
        self.assertNotIn("xác nhận đặt hàng", answer.prompt)
        db.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
