import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business
from app.models.customer import Customer
from app.models.customer_collection import (
    CustomerAddress,
    CustomerCollectionSession,
    CustomerContact,
)
from app.models.message import Message
from app.models.notification import Notification
from app.models.conversation import Conversation
from app.models.chatbot_followup import ChatbotFollowUp
from app.models.sales import Order, Product
from app.services.customer_collection_flow import (
    _store_address,
    _store_contact,
    advance_customer_collection,
    is_browsing_request,
    is_greeting,
    is_order_intent,
    is_price_quote_request,
    is_stock_query_request,
)
from app.services.customer_collection import contact_hash


class CustomerCollectionFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Flow Shop", slug="flow-shop")
            db.add(business)
            db.flush()
            customer = Customer(
                business_id=business.id,
                channel="facebook",
                external_user_id="flow-user",
                name=None,
            )
            db.add(customer)
            db.add(Product(
                business_id=business.id,
                sku="SERUM-001",
                name="Serum",
                price=Decimal("200000"),
                stock_quantity=11,
                reserved_quantity=0,
                status="active",
            ))
            db.add(Product(
                business_id=business.id,
                sku="BIN-001",
                name="bin",
                price=Decimal("1000000"),
                stock_quantity=18,
                reserved_quantity=0,
                status="active",
            ))
            db.add(Product(
                business_id=business.id,
                sku="COMBO-01",
                name="Combo chăm sóc da cơ bản",
                price=Decimal("799000"),
                stock_quantity=6,
                reserved_quantity=0,
                metadata_={"aliases": ["combo cơ bản", "bộ chăm sóc da cơ bản"]},
                status="active",
            ))
            db.add(Product(
                business_id=business.id,
                sku="SERUM-C-01",
                name="Serum Vitamin C Lunari",
                price=Decimal("420000"),
                stock_quantity=10,
                reserved_quantity=0,
                status="active",
            ))
            db.add(Product(
                business_id=business.id,
                sku="CLEANSER-01",
                name="Sữa rửa mặt dịu nhẹ",
                price=Decimal("179000"),
                stock_quantity=18,
                reserved_quantity=0,
                status="active",
            ))
            db.add(Product(
                business_id=business.id,
                sku="SUN-01",
                name="Kem chống nắng Daily Shield",
                price=Decimal("289000"),
                stock_quantity=25,
                reserved_quantity=0,
                status="active",
            ))
            db.commit()
            cls.business_id = business.id
            cls.customer_id = customer.id

    def setUp(self):
        # Drafts now hold inventory temporarily.  Reset the shared fixture so
        # each scenario starts from the documented catalog quantities instead
        # of inheriting another test's reservation.
        with Session(self.engine) as db:
            for product in db.query(Product).filter(Product.business_id == self.business_id).all():
                product.reserved_quantity = 0
            for order in db.query(Order).filter(Order.business_id == self.business_id, Order.status == "draft").all():
                order.reserved_quantity = 0
                order.reservation_expires_at = None
                metadata = dict(order.metadata_ or {})
                metadata["reservation_status"] = "test_reset"
                order.metadata_ = metadata
            db.commit()

    def test_progressive_collection_persists_each_step(self):
        with Session(self.engine) as db:
            customer = db.get(Customer, self.customer_id)
            customer.name = None
            customer.email = None
            customer.phone = None
            customer.address = None
            db.commit()

            first = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=11,
                source_channel="facebook",
                text="Mình muốn đặt hàng áo này",
            )
            self.assertTrue(first.started)
            self.assertEqual("name", first.current_field)

            second = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=11,
                source_channel="facebook",
                text="Nguyễn Văn A",
            )
            self.assertEqual("phone", second.current_field)

            third = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=11,
                source_channel="facebook",
                text="090 123 4567",
            )
            self.assertEqual("email", third.current_field)

            email = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=11,
                source_channel="facebook",
                text="nguyen.van.a@example.com",
            )
            self.assertEqual("address", email.current_field)

            fourth = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=11,
                source_channel="facebook",
                text="12 Nguyễn Huệ, phường Bến Nghé, Quận 1, TP.HCM",
            )
            self.assertEqual("payment_method", fourth.current_field)

            completed = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=11,
                source_channel="facebook",
                text="Thanh toán COD",
            )
            self.assertTrue(completed.completed)
            self.assertIsNone(completed.current_field)

            session = db.query(CustomerCollectionSession).filter_by(conversation_id=11).one()
            self.assertEqual("completed", session.status)
            self.assertEqual("Nguyễn Văn A", session.collected_fields["name"])
            self.assertEqual("nguyen.van.a@example.com", session.collected_fields["email"])
            self.assertEqual("cod", session.collected_fields["payment_method"])
            customer = db.get(Customer, self.customer_id)
            self.assertEqual("Nguyễn Văn A", customer.name)
            self.assertEqual("nguyen.van.a@example.com", customer.email)
            self.assertEqual(1, db.query(CustomerContact).filter_by(customer_id=self.customer_id, kind="phone").count())
            self.assertEqual(1, db.query(CustomerContact).filter_by(customer_id=self.customer_id, kind="email").count())
            self.assertEqual(1, db.query(CustomerAddress).filter_by(customer_id=self.customer_id).count())

    def test_interrupted_session_resumes_and_non_order_text_is_ignored(self):
        with Session(self.engine) as db:
            ignored = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=21,
                source_channel="telegram",
                text="Cho mình hỏi màu xanh còn không?",
            )
            self.assertIsNone(ignored)

            started = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=21,
                source_channel="telegram",
                text="Chốt đơn giúp mình",
            )
            self.assertTrue(started.started)
            db.commit()

        with Session(self.engine) as db:
            resumed = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=21,
                source_channel="telegram",
                text="Trần B",
            )
            self.assertEqual("phone", resumed.current_field)
            self.assertEqual(1, db.query(CustomerCollectionSession).filter_by(conversation_id=21).count())

    def test_collection_waits_until_customer_confirms_a_specific_product(self):
        self.assertFalse(is_order_intent("Tôi cần mua hàng"))
        self.assertFalse(is_order_intent("Tôi cần tìm hiểu danh sách sản phẩm"))
        self.assertTrue(is_order_intent("Mình muốn đặt hàng áo này"))
        self.assertTrue(is_order_intent("Mình mua sản phẩm này"))
        self.assertTrue(is_order_intent("Mình chốt áo này"))

        with Session(self.engine) as db:
            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=31,
                source_channel="zalo",
                text="Tôi cần mua hàng",
            )
            self.assertIsNone(result)
            self.assertEqual(0, db.query(CustomerCollectionSession).filter_by(conversation_id=31).count())

            started = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=32,
                source_channel="zalo",
                text="Mình mua sản phẩm này",
            )
            self.assertTrue(started.started)
            browse = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=32,
                source_channel="zalo",
                text="Tôi cần tìm hiểu danh sách sản phẩm",
            )
            self.assertIsNone(browse)
            session = db.query(CustomerCollectionSession).filter_by(conversation_id=32).one()
            self.assertEqual("abandoned", session.status)

    def test_greeting_is_detected_without_treating_product_questions_as_greetings(self):
        self.assertTrue(is_greeting("alo"))
        self.assertTrue(is_greeting("Xin chào bạn!"))
        self.assertTrue(is_greeting("hello"))
        self.assertFalse(is_greeting("alo, cho tôi xem sản phẩm"))
        self.assertFalse(is_greeting("tôi muốn mua Daily Shield"))

    def test_greeting_does_not_resume_a_stale_collection_prompt(self):
        with Session(self.engine) as db:
            started = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=41,
                source_channel="zalo",
                text="Mình chốt sản phẩm này",
            )
            self.assertTrue(started.started)

            greeting = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=41,
                source_channel="zalo",
                text="alo",
            )

            self.assertIsNone(greeting)
            session = db.query(CustomerCollectionSession).filter_by(conversation_id=41).one()
            self.assertEqual("name", session.current_field)
            self.assertEqual("pending", session.status)

    def test_repeated_contacts_and_addresses_are_normalized_and_reused(self):
        with Session(self.engine) as db:
            _store_contact(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                kind="email",
                value=" Flow.User@Example.com ",
            )
            _store_contact(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                kind="email",
                value="flow.user@example.com",
            )
            _store_address(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                value=" 12 Nguyen Hue, Quan 1 ",
            )
            _store_address(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                value="12 Nguyen Hue, Quan 1",
            )
            db.commit()

            contacts = db.query(CustomerContact).filter(
                CustomerContact.business_id == self.business_id,
                CustomerContact.customer_id == self.customer_id,
                CustomerContact.kind == "email",
                CustomerContact.value_hash == contact_hash("email", "flow.user@example.com"),
            ).all()
            addresses = db.query(CustomerAddress).filter(
                CustomerAddress.business_id == self.business_id,
                CustomerAddress.customer_id == self.customer_id,
                CustomerAddress.address_line1 == "12 Nguyen Hue, Quan 1",
            ).all()

        self.assertEqual(1, len(contacts))
        self.assertTrue(contacts[0].is_primary)
        self.assertEqual(1, len(addresses))
        self.assertTrue(addresses[0].is_default)

    def test_product_discovery_is_detected_even_with_natural_language(self):
        self.assertTrue(is_browsing_request("Bạn có sản phẩm gì?"))
        self.assertTrue(is_browsing_request("Cho mình xem hàng với"))
        self.assertTrue(is_browsing_request("Shop còn mẫu nào không?"))
        self.assertTrue(is_browsing_request("Tôi muốn mua sản phẩm bạn có gì"))
        self.assertFalse(is_browsing_request("Mình chốt sản phẩm này"))
        self.assertFalse(is_browsing_request("Mình chốt sản phẩm nào"))

    def test_quantity_price_question_is_not_order_confirmation(self):
        self.assertTrue(is_price_quote_request("Tôi muốn mua bin 20 sản phẩm thì giá như nào"))
        self.assertTrue(is_price_quote_request("giá của 18 cái bin"))
        self.assertTrue(is_stock_query_request("tôi muốn mua 20 cái bin bạn có không"))
        self.assertFalse(is_order_intent("Tôi muốn mua sản phẩm bạn có gì"))
        self.assertFalse(is_order_intent("tôi muốn mua 20 cái bin bạn có không"))

    def test_product_discovery_does_not_start_checkout(self):
        with Session(self.engine) as db:
            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=52,
                source_channel="instagram",
                text="Tôi muốn mua sản phẩm bạn có gì",
            )

            self.assertIsNone(result)
            self.assertEqual(
                0,
                db.query(CustomerCollectionSession).filter_by(conversation_id=52).count(),
            )

    def test_named_product_purchase_starts_product_only_quote(self):
        with Session(self.engine) as db:
            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=121,
                source_channel="facebook",
                text="Tôi muốn mua 3 sản phẩm Kem chống nắng Daily Shield",
            )

        self.assertIsNotNone(result)
        self.assertTrue(result.started)
        self.assertEqual("order_confirmation", result.current_field)
        self.assertIn("3 Kem chống nắng Daily Shield", result.prompt)
        self.assertIn("867.000 đồng", result.prompt)
        self.assertNotIn("Danh sách sản phẩm", result.prompt)

    def test_natural_language_price_question_starts_quote_before_checkout(self):
        with Session(self.engine) as db:
            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=53,
                source_channel="instagram",
                text="Tôi muốn mua 2 Serum thì giá như nào",
            )

            self.assertTrue(result.started)
            self.assertEqual("order_confirmation", result.current_field)
            self.assertIn("400.000 đồng", result.prompt)

    def test_product_purchase_without_quantity_uses_one_as_the_safe_default(self):
        with Session(self.engine) as db:
            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=59,
                source_channel="telegram",
                text="Mình muốn mua Serum",
            )

            self.assertEqual("order_confirmation", result.current_field)
            self.assertIn("mua 1 Serum", result.prompt)
            self.assertNotIn("mua 0 Serum", result.prompt)

    def test_stock_question_reports_availability_before_collecting_customer_data(self):
        with Session(self.engine) as db:
            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=54,
                source_channel="instagram",
                text="tôi muốn mua 20 cái bin bạn có không",
            )

            self.assertTrue(result.started)
            self.assertEqual("stock_unavailable", result.status)
            self.assertIsNone(result.current_field)
            self.assertIn("chỉ còn 18", result.prompt)
            self.assertEqual(
                0,
                db.query(CustomerCollectionSession).filter_by(conversation_id=54).count(),
            )

    def test_price_of_quantity_starts_quote_before_collecting_customer_data(self):
        with Session(self.engine) as db:
            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=55,
                source_channel="instagram",
                text="giá của 18 cái bin",
            )

            self.assertTrue(result.started)
            self.assertEqual("order_confirmation", result.current_field)
            self.assertIn("18.000.000 đồng", result.prompt)

    def test_price_question_replaces_stale_checkout_session(self):
        with Session(self.engine) as db:
            started = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=56,
                source_channel="instagram",
                text="Mình chốt sản phẩm này",
            )
            self.assertTrue(started.started)

            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=56,
                source_channel="instagram",
                text="giá của 18 cái bin",
            )

            self.assertEqual("order_confirmation", result.current_field)
            self.assertIn("18.000.000 đồng", result.prompt)
            sessions = db.query(CustomerCollectionSession).filter_by(conversation_id=56).all()
            self.assertEqual(["abandoned", "pending"], [item.status for item in sessions])

    def test_product_question_abandons_pending_checkout_at_any_field(self):
        with Session(self.engine) as db:
            started = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=51,
                source_channel="zalo",
                text="Mình chốt sản phẩm này",
            )
            self.assertTrue(started.started)
            advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=51,
                source_channel="zalo",
                text="Nguyễn Văn A",
            )

            browse = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=51,
                source_channel="zalo",
                text="Bạn có sản phẩm gì?",
            )

            self.assertIsNone(browse)
            session = db.query(CustomerCollectionSession).filter_by(conversation_id=51).one()
            self.assertEqual("abandoned", session.status)
            self.assertIsNone(session.current_field)

    def test_price_question_quotes_total_before_collecting_customer_data(self):
        with Session(self.engine) as db:
            quote = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=61,
                source_channel="instagram",
                text="Tôi muốn mua 11 Serum thì hết bao nhiêu tiền?",
            )

            self.assertTrue(quote.started)
            self.assertEqual("order_confirmation", quote.current_field)
            self.assertIn("2.200.000 đồng", quote.prompt)
            self.assertIn("còn 11", quote.prompt)

            session = db.query(CustomerCollectionSession).filter_by(conversation_id=61).one()
            self.assertEqual("order_confirmation", session.purpose)
            self.assertEqual("Serum", session.collected_fields["product_name"])
            self.assertEqual(11, session.collected_fields["quantity"])
            self.assertEqual("2200000.00", session.collected_fields["total_amount"])

            confirmed = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=61,
                source_channel="instagram",
                text="Đồng ý, chốt đơn",
            )

            self.assertEqual("name", confirmed.current_field)
            self.assertIn("tên người nhận", confirmed.prompt)
            self.assertEqual("order", session.purpose)
            self.assertEqual(list(("name", "phone", "email", "address", "payment_method")), session.required_fields)

    def test_confirmed_product_checkout_creates_one_draft_order(self):
        """Catch a regression where completed chat checkout is not made actionable in CRM."""
        with Session(self.engine) as db:
            checkout_customer = Customer(
                business_id=self.business_id,
                channel="telegram",
                external_user_id="checkout-order-user",
                name=None,
            )
            db.add(checkout_customer)
            db.flush()
            quote = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=checkout_customer.id,
                conversation_id=89,
                source_channel="telegram",
                text="giá của 2 Serum hết bao nhiêu",
            )
            self.assertEqual("order_confirmation", quote.current_field)

            self.assertEqual("name", advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=checkout_customer.id,
                conversation_id=89,
                source_channel="telegram",
                text="Đồng ý đặt hàng",
            ).current_field)
            advance_customer_collection(db, business_id=self.business_id, customer_id=checkout_customer.id, conversation_id=89, source_channel="telegram", text="Nguyễn Mai")
            advance_customer_collection(db, business_id=self.business_id, customer_id=checkout_customer.id, conversation_id=89, source_channel="telegram", text="0912345678")
            advance_customer_collection(db, business_id=self.business_id, customer_id=checkout_customer.id, conversation_id=89, source_channel="telegram", text="mai@example.com")
            advance_customer_collection(db, business_id=self.business_id, customer_id=checkout_customer.id, conversation_id=89, source_channel="telegram", text="12 Nguyễn Huệ, Quận 1")
            completed = advance_customer_collection(db, business_id=self.business_id, customer_id=checkout_customer.id, conversation_id=89, source_channel="telegram", text="COD")

            self.assertTrue(completed.completed)
            self.assertIsNotNone(completed.draft_order_id)
            order = db.query(Order).filter_by(conversation_id=89).one()
            self.assertEqual("draft", order.status)
            self.assertEqual(Decimal("400000"), order.total_amount)
            self.assertEqual("Serum", order.items[0].product_name_snapshot)
            self.assertEqual(2, order.items[0].quantity)
            self.assertEqual("chatbot_collection", order.metadata_["source"])
            notifications = db.query(Notification).filter_by(
                business_id=self.business_id,
                kind="chatbot_order_draft",
            ).all()
            self.assertEqual(1, len(notifications))
            self.assertEqual("Đơn nháp chatbot cần xác nhận", notifications[0].title)
            self.assertEqual(order.id, notifications[0].metadata_["order_id"])
            self.assertEqual(89, notifications[0].metadata_["conversation_id"])

            # Repeated provider delivery after the completed session must not
            # create a duplicate draft order.
            advance_customer_collection(db, business_id=self.business_id, customer_id=checkout_customer.id, conversation_id=89, source_channel="telegram", text="COD")
            self.assertEqual(1, db.query(Order).filter_by(conversation_id=89).count())
            self.assertEqual(1, db.query(Notification).filter_by(
                business_id=self.business_id,
                kind="chatbot_order_draft",
            ).count())

    def test_combo_alias_quotes_from_product_database(self):
        with Session(self.engine) as db:
            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=57,
                source_channel="instagram",
                text="giá của 6 bộ combo cơ bản hết bao nhiêu",
            )

            self.assertTrue(result.started)
            self.assertEqual("order_confirmation", result.current_field)
            self.assertIn("4.794.000 đồng", result.prompt)

    def test_customer_can_switch_from_combo_to_single_product_before_checkout(self):
        with Session(self.engine) as db:
            quote = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=58,
                source_channel="instagram",
                text="Tôi muốn mua combo chăm sóc da cơ bản",
            )
            self.assertEqual("order_confirmation", quote.current_field)
            self.assertIn("799.000 đồng", quote.prompt)

            switched = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=58,
                source_channel="instagram",
                text="không, tôi muốn mua sữa rửa mặt",
            )

            self.assertEqual("order_confirmation", switched.current_field)
            self.assertIn("Sữa rửa mặt dịu nhẹ", switched.prompt)
            self.assertIn("179.000 đồng", switched.prompt)
            self.assertNotIn("Combo chăm sóc da cơ bản", switched.prompt)

    def test_multi_product_quote_merges_follow_up_and_creates_multi_item_draft(self):
        with Session(self.engine) as db:
            checkout_customer = Customer(
                business_id=self.business_id,
                channel="zalo",
                external_user_id="multi-product-user",
                name=None,
            )
            db.add(checkout_customer)
            db.flush()

            quote = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=checkout_customer.id,
                conversation_id=96,
                source_channel="zalo",
                text="Tôi muốn mua Serum Vitamin C Lunari và sữa rửa mặt dịu nhẹ",
            )
            self.assertEqual("order_confirmation", quote.current_field)
            self.assertIn("599.000 đồng", quote.prompt)

            added = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=checkout_customer.id,
                conversation_id=96,
                source_channel="zalo",
                text="và mua thêm 1 Serum Vitamin C Lunari",
            )
            self.assertEqual("order_confirmation", added.current_field)
            self.assertIn("1.019.000 đồng", added.prompt)
            self.assertIn("2 Serum Vitamin C Lunari", added.prompt)
            self.assertIn("1 Sữa rửa mặt dịu nhẹ", added.prompt)

            self.assertEqual("name", advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=checkout_customer.id,
                conversation_id=96,
                source_channel="zalo",
                text="Đồng ý đặt hàng",
            ).current_field)
            advance_customer_collection(db, business_id=self.business_id, customer_id=checkout_customer.id, conversation_id=96, source_channel="zalo", text="Nguyễn Mai")
            advance_customer_collection(db, business_id=self.business_id, customer_id=checkout_customer.id, conversation_id=96, source_channel="zalo", text="0912345678")
            advance_customer_collection(db, business_id=self.business_id, customer_id=checkout_customer.id, conversation_id=96, source_channel="zalo", text="mai96@example.com")
            advance_customer_collection(db, business_id=self.business_id, customer_id=checkout_customer.id, conversation_id=96, source_channel="zalo", text="12 Nguyễn Huệ, Quận 1")
            completed = advance_customer_collection(db, business_id=self.business_id, customer_id=checkout_customer.id, conversation_id=96, source_channel="zalo", text="COD")

            self.assertTrue(completed.completed)
            order = db.query(Order).filter_by(conversation_id=96).one()
            self.assertEqual(Decimal("1019000"), order.total_amount)
            self.assertEqual(
                {"Serum Vitamin C Lunari": 2, "Sữa rửa mặt dịu nhẹ": 1},
                {item.product_name_snapshot: item.quantity for item in order.items},
            )

    def test_multi_product_addition_refreshes_legacy_quote_stock(self):
        with Session(self.engine) as db:
            checkout_customer = Customer(
                business_id=self.business_id,
                channel="zalo",
                external_user_id="legacy-multi-product-user",
                name=None,
            )
            db.add(checkout_customer)
            db.flush()

            quote = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=checkout_customer.id,
                conversation_id=97,
                source_channel="zalo",
                text="Mình muốn mua Serum",
            )
            self.assertEqual("order_confirmation", quote.current_field)
            session = db.query(CustomerCollectionSession).filter_by(conversation_id=97).one()
            legacy_fields = dict(session.collected_fields)
            legacy_fields.pop("items", None)
            legacy_fields.pop("available", None)
            session.collected_fields = legacy_fields
            db.commit()

            added = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=checkout_customer.id,
                conversation_id=97,
                source_channel="zalo",
                text="và mua thêm 1 bin",
            )
            self.assertEqual("order_confirmation", added.current_field)
            self.assertIn("1.200.000 đồng", added.prompt)
            self.assertIn("1 Serum", added.prompt)
            self.assertIn("1 bin", added.prompt)

    def test_partial_product_names_are_merged_in_quote_and_follow_up(self):
        with Session(self.engine) as db:
            checkout_customer = Customer(
                business_id=self.business_id,
                channel="zalo",
                external_user_id="partial-multi-product-user",
                name=None,
            )
            db.add(checkout_customer)
            db.flush()

            quote = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=checkout_customer.id,
                conversation_id=98,
                source_channel="zalo",
                text="tôi muốn mua 2 kem chống nắng và 1 sữa rửa mặt",
            )
            self.assertEqual("order_confirmation", quote.current_field)
            self.assertIn("757.000 đồng", quote.prompt)
            self.assertIn("2 Kem chống nắng Daily Shield", quote.prompt)
            self.assertIn("1 Sữa rửa mặt dịu nhẹ", quote.prompt)

            added = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=checkout_customer.id,
                conversation_id=98,
                source_channel="zalo",
                text="và mua thêm 1 sữa mặt",
            )
            self.assertEqual("order_confirmation", added.current_field)
            self.assertIn("936.000 đồng", added.prompt)
            self.assertIn("2 Sữa rửa mặt dịu nhẹ", added.prompt)

    def test_quote_schedules_abandoned_reminder_and_confirmation_cancels_it(self):
        with Session(self.engine) as db:
            customer = Customer(
                business_id=self.business_id,
                channel="telegram",
                external_user_id="abandoned-reminder-user",
                name=None,
            )
            db.add(customer)
            db.flush()
            conversation = Conversation(
                business_id=self.business_id,
                customer_id=customer.id,
                channel="telegram",
            )
            db.add(conversation)
            db.flush()

            quote = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=customer.id,
                conversation_id=conversation.id,
                source_channel="telegram",
                text="giá của 2 Serum hết bao nhiêu",
            )
            reminder = db.query(ChatbotFollowUp).filter_by(
                business_id=self.business_id,
                conversation_id=conversation.id,
                kind="cart_abandoned",
            ).one()
            self.assertEqual(quote.session_id, reminder.metadata_["collection_session_id"])
            self.assertEqual("scheduled", reminder.status)

            advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=customer.id,
                conversation_id=conversation.id,
                source_channel="telegram",
                text="Đồng ý đặt hàng",
            )
            self.assertEqual("cancelled", reminder.status)

    def test_short_follow_up_uses_last_customer_product_mention(self):
        with Session(self.engine) as db:
            db.add(Message(
                conversation_id=58,
                channel="instagram",
                direction="inbound",
                content="Bạn có bao nhiêu combo chăm sóc da cơ bản?",
            ))
            db.commit()

            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=58,
                source_channel="instagram",
                text="giá của 6 bộ đó hết bao nhiêu",
            )

            self.assertEqual("order_confirmation", result.current_field)
            self.assertIn("4.794.000 đồng", result.prompt)

    def test_price_question_reports_insufficient_stock_without_starting_checkout(self):
        with Session(self.engine) as db:
            quote = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=62,
                source_channel="zalo",
                text="Mua 12 Serum hết bao nhiêu?",
            )

            self.assertTrue(quote.started)
            self.assertIsNone(quote.current_field)
            self.assertIn("chỉ còn 11", quote.prompt)
            self.assertEqual(0, db.query(CustomerCollectionSession).filter_by(conversation_id=62).count())


if __name__ == "__main__":
    unittest.main()
