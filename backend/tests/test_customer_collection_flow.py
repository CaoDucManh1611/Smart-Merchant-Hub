import unittest
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business
from app.models.customer import Customer
from app.models.customer_collection import (
    CustomerAddress,
    CustomerCollectionSession,
    CustomerContact,
    CustomerVerificationChallenge,
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
    greeting_reply,
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
            self.assertIn("số điện thoại", second.prompt)

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
            self.assertEqual("+84901234567", session.collected_fields["phone"])
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

    def test_shopee_checkout_asks_for_email_without_phone(self):
        with Session(self.engine) as db:
            customer = Customer(
                business_id=self.business_id,
                channel="shopee",
                external_user_id="email-only-checkout-user",
            )
            db.add(customer)
            db.flush()
            conversation_id = 22

            self.assertEqual("name", advance_customer_collection(
                db, business_id=self.business_id, customer_id=customer.id,
                conversation_id=conversation_id, source_channel="shopee",
                text="Chốt đơn giúp mình",
            ).current_field)
            contact = advance_customer_collection(
                db, business_id=self.business_id, customer_id=customer.id,
                conversation_id=conversation_id, source_channel="shopee",
                text="Lê Mai",
            )
            self.assertEqual("email", contact.current_field)
            self.assertIn("email", contact.prompt)
            self.assertNotIn("số điện thoại", contact.prompt)

            invalid_phone = advance_customer_collection(
                db, business_id=self.business_id, customer_id=customer.id,
                conversation_id=conversation_id, source_channel="shopee",
                text="0901234567",
            )
            self.assertEqual("email", invalid_phone.current_field)

            address = advance_customer_collection(
                db, business_id=self.business_id, customer_id=customer.id,
                conversation_id=conversation_id, source_channel="shopee",
                text="mai.checkout@example.com",
            )
            self.assertEqual("address", address.current_field)
            session = db.query(CustomerCollectionSession).filter_by(conversation_id=conversation_id).one()
            self.assertEqual(["name", "email", "address", "payment_method"], session.required_fields)
            self.assertEqual("mai.checkout@example.com", customer.email)
            self.assertIsNone(customer.phone)

    def test_legacy_shopee_contact_session_is_upgraded_to_email_only(self):
        with Session(self.engine) as db:
            customer = Customer(
                business_id=self.business_id,
                channel="shopee",
                external_user_id="legacy-phone-checkout-user",
            )
            db.add(customer)
            db.flush()
            session = CustomerCollectionSession(
                business_id=self.business_id,
                customer_id=customer.id,
                conversation_id=23,
                purpose="order",
                required_fields=["name", "contact", "address", "payment_method"],
                collected_fields={"name": "An", "phone": "0901234567", "contact": "phone", "reply_language": "vi"},
                current_field="address",
                source_channel="shopee",
                status="partial",
            )
            db.add(session)
            db.flush()

            result = advance_customer_collection(
                db, business_id=self.business_id, customer_id=customer.id,
                conversation_id=23, source_channel="shopee",
                text="an@example.com",
            )

            self.assertEqual("address", result.current_field)
            self.assertEqual(["name", "email", "address", "payment_method"], session.required_fields)
            self.assertEqual("0901234567", session.collected_fields["phone"])
            self.assertEqual("an@example.com", session.collected_fields["email"])

    def test_shopee_email_checkout_stays_pending_when_only_sms_otp_is_configured(self):
        with Session(self.engine) as db:
            customer = Customer(
                business_id=self.business_id,
                channel="shopee",
                external_user_id="shopee-sms-only-otp-user",
            )
            db.add(customer)
            db.flush()
            conversation_id = 24
            quote = advance_customer_collection(
                db, business_id=self.business_id, customer_id=customer.id,
                conversation_id=conversation_id, source_channel="shopee",
                text="giá của 1 Serum hết bao nhiêu",
            )
            self.assertEqual("order_confirmation", quote.current_field)
            self.assertEqual("name", advance_customer_collection(
                db, business_id=self.business_id, customer_id=customer.id,
                conversation_id=conversation_id, source_channel="shopee",
                text="Đồng ý đặt hàng",
            ).current_field)
            advance_customer_collection(
                db, business_id=self.business_id, customer_id=customer.id,
                conversation_id=conversation_id, source_channel="shopee",
                text="Trần An",
            )
            self.assertEqual("address", advance_customer_collection(
                db, business_id=self.business_id, customer_id=customer.id,
                conversation_id=conversation_id, source_channel="shopee",
                text="an.shopee@example.com",
            ).current_field)
            self.assertEqual("payment_method", advance_customer_collection(
                db, business_id=self.business_id, customer_id=customer.id,
                conversation_id=conversation_id, source_channel="shopee",
                text="12 Nguyễn Huệ, Quận 1",
            ).current_field)

            with patch("app.services.customer_collection_flow.settings.OTP_DELIVERY_MODE", "twilio"):
                result = advance_customer_collection(
                    db, business_id=self.business_id, customer_id=customer.id,
                    conversation_id=conversation_id, source_channel="shopee",
                    text="COD",
                )

            session = db.query(CustomerCollectionSession).filter_by(conversation_id=conversation_id).one()
            order = db.query(Order).filter_by(conversation_id=conversation_id).one()
            challenge = db.query(CustomerVerificationChallenge).filter_by(customer_id=customer.id).one()
            self.assertIn("chưa gửi OTP thành công", result.prompt)
            self.assertTrue(session.collected_fields["otp_pending"])
            self.assertTrue(session.collected_fields["otp_delivery_pending"])
            self.assertFalse(session.collected_fields["awaiting_customer_confirmation"])
            self.assertEqual("email", challenge.channel)
            self.assertEqual("queued", challenge.status)
            self.assertTrue(order.metadata_["contact_verification_pending"])

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
        self.assertEqual(
            "Hi! I can help you find a product or answer questions about an order today.",
            greeting_reply("hello"),
        )
        self.assertIn("Chào bạn", greeting_reply("xin chào"))

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
        self.assertTrue(is_browsing_request("I want to buy product"))
        self.assertTrue(is_browsing_request("What products do you have?"))
        self.assertFalse(is_order_intent("I want to buy product"))

    def test_recent_cancelled_quote_question_is_answered_without_starting_checkout(self):
        with Session(self.engine) as db:
            quote = CustomerCollectionSession(
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=529,
                purpose="order_confirmation",
                required_fields=["confirmation"],
                collected_fields={
                    "items": [{
                        "product_id": db.query(Product.id).filter_by(
                            business_id=self.business_id,
                            sku="SERUM-001",
                        ).scalar(),
                        "product_name": "Serum",
                        "quantity": 2,
                        "unit_price": "200000",
                    }],
                    "total_amount": "400000",
                    "confirmation_status": "declined",
                },
                current_field=None,
                source_channel="telegram",
                status="abandoned",
            )
            db.add(quote)
            db.commit()

            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=529,
                source_channel="telegram",
                text="hỏi nãy tôi vừa mua gì",
            )

            self.assertEqual("history_answer", result.status)
            self.assertIn("2 Serum", result.prompt)
            self.assertIn("400.000 đồng", result.prompt)
            self.assertIn("chưa có đơn hàng được xác nhận", result.prompt)
            self.assertEqual(
                1,
                db.query(CustomerCollectionSession).filter_by(conversation_id=529).count(),
            )

    def test_quantity_price_question_is_not_order_confirmation(self):
        self.assertTrue(is_price_quote_request("Tôi muốn mua bin 20 sản phẩm thì giá như nào"))
        self.assertTrue(is_price_quote_request("giá của 18 cái bin"))
        self.assertTrue(is_stock_query_request("tôi muốn mua 20 cái bin bạn có không"))
        self.assertTrue(is_stock_query_request("Serum còn hàng không ạ?"))
        self.assertTrue(is_stock_query_request("Mẫu 1.8 lít còn hàng không?"))
        self.assertFalse(is_price_quote_request("Điện gia dụng mẫu 01 giá bao nhiêu và còn bao nhiêu sản phẩm"))
        self.assertFalse(is_order_intent("Tôi muốn mua sản phẩm bạn có gì"))
        self.assertFalse(is_order_intent("tôi muốn mua 20 cái bin bạn có không"))

    def test_model_number_price_question_does_not_start_checkout(self):
        with Session(self.engine) as db:
            db.add(Product(
                business_id=self.business_id,
                sku="HOME-01",
                name="Điện gia dụng mẫu 01",
                price=Decimal("349000"),
                stock_quantity=138,
                reserved_quantity=0,
                status="active",
            ))
            db.commit()
            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=122,
                source_channel="telegram",
                text="Điện gia dụng mẫu 01 giá bao nhiêu và còn bao nhiêu sản phẩm",
            )

        self.assertIsNone(result)

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

    def test_customer_can_change_the_quantity_of_a_single_pending_quote(self):
        with Session(self.engine) as db:
            quote = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=590,
                source_channel="telegram",
                text="Mình muốn mua Kem chống nắng Daily Shield",
            )
            self.assertIn("mua 1 Kem chống nắng Daily Shield", quote.prompt)

            revised = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=590,
                source_channel="telegram",
                text="tôi muốn mua 20 cái",
            )

            self.assertIn("mua 20 Kem chống nắng Daily Shield", revised.prompt)
            self.assertIn("5.780.000 đồng", revised.prompt)
            session = db.query(CustomerCollectionSession).filter_by(conversation_id=590).one()
            self.assertEqual(20, session.collected_fields["quantity"])

    def test_explicit_quantity_correction_replaces_but_add_more_increments(self):
        with Session(self.engine) as db:
            quote = advance_customer_collection(
                db, business_id=self.business_id, customer_id=self.customer_id,
                conversation_id=5901, source_channel="shopee",
                text="Mình muốn mua 2 Serum",
            )
            self.assertIn("mua 2 Serum", quote.prompt)

            corrected = advance_customer_collection(
                db, business_id=self.business_id, customer_id=self.customer_id,
                conversation_id=5901, source_channel="shopee",
                text="À mình đổi thành 3 Serum, tính lại giúp mình. Chưa xác nhận mua nhé.",
            )
            self.assertIn("mua 3 Serum", corrected.prompt)
            self.assertIn("600.000 đồng", corrected.prompt)
            session = db.query(CustomerCollectionSession).filter_by(conversation_id=5901).one()
            self.assertEqual(3, session.collected_fields["quantity"])

            added = advance_customer_collection(
                db, business_id=self.business_id, customer_id=self.customer_id,
                conversation_id=5901, source_channel="shopee",
                text="Thêm 2 Serum nữa nhé",
            )
            self.assertIn("mua 5 Serum", added.prompt)

            corrected_from = advance_customer_collection(
                db, business_id=self.business_id, customer_id=self.customer_id,
                conversation_id=5901, source_channel="shopee",
                text="Mình đổi từ 5 thành 3 Serum nhé",
            )
            self.assertIn("mua 3 Serum", corrected_from.prompt)

            decreased = advance_customer_collection(
                db, business_id=self.business_id, customer_id=self.customer_id,
                conversation_id=5901, source_channel="shopee",
                text="Bớt 1 Serum nhé",
            )
            self.assertIn("mua 2 Serum", decreased.prompt)
            self.assertIn("400.000 đồng", decreased.prompt)

            invalid = advance_customer_collection(
                db, business_id=self.business_id, customer_id=self.customer_id,
                conversation_id=5901, source_channel="shopee",
                text="Bớt 3 Serum nhé",
            )
            self.assertIn("ít nhất 1", invalid.prompt)
            db.refresh(session)
            self.assertEqual(2, session.collected_fields["quantity"])

            product = db.query(Product).filter_by(business_id=self.business_id, name="Serum").one()
            product.price = Decimal("210000")
            db.commit()
            repriced = advance_customer_collection(
                db, business_id=self.business_id, customer_id=self.customer_id,
                conversation_id=5901, source_channel="shopee",
                text="Đổi thành 3 Serum nhé",
            )
            self.assertIn("630.000 đồng", repriced.prompt)

            accepted = advance_customer_collection(
                db, business_id=self.business_id, customer_id=self.customer_id,
                conversation_id=5901, source_channel="shopee", text="Xác nhận",
            )
            self.assertEqual("partial", accepted.status)
            changed_after_acceptance = advance_customer_collection(
                db, business_id=self.business_id, customer_id=self.customer_id,
                conversation_id=5901, source_channel="shopee", text="Thêm 3 nữa",
            )
            self.assertIn("mua 6 Serum", changed_after_acceptance.prompt)
            db.refresh(session)
            self.assertEqual("order_confirmation", session.purpose)
            self.assertEqual(6, session.collected_fields["quantity"])
            product.price = Decimal("200000")
            db.commit()

    def test_commerce_corpus_dialogues_never_create_orders_before_checkout_verification(self):
        corpus_path = Path(__file__).resolve().parents[2] / "docs" / "commerce-nlu-evaluation-set.json"
        dialogues = [
            case for case in json.loads(corpus_path.read_text(encoding="utf-8"))["cases"]
            if case["type"] == "dialogue"
        ]
        with Session(self.engine) as db:
            db.add_all([
                Product(
                    business_id=self.business_id,
                    sku="EVAL-MODEL-01",
                    name="Điện gia dụng mẫu 01",
                    price=Decimal("349000"),
                    stock_quantity=230,
                    reserved_quantity=0,
                    metadata_={"aliases": ["household appliance model 01", "model 01"]},
                    status="active",
                ),
                Product(
                    business_id=self.business_id,
                    sku="EVAL-MODEL-02",
                    name="Điện gia dụng mẫu 02",
                    price=Decimal("169000"),
                    stock_quantity=330,
                    reserved_quantity=0,
                    metadata_={"aliases": ["household appliance model 02", "model 02"]},
                    status="active",
                ),
                Product(
                    business_id=self.business_id,
                    sku="EVAL-LONA-M-BLACK",
                    name="Áo khoác Lona màu đen size M",
                    price=Decimal("500000"),
                    stock_quantity=12,
                    reserved_quantity=0,
                    metadata_={"aliases": ["Lona jacket black size M"]},
                    status="active",
                ),
            ])
            db.commit()

            for index, dialogue in enumerate(dialogues, start=1):
                conversation_id = 91000 + index
                for turn in dialogue["turns"]:
                    advance_customer_collection(
                        db,
                        business_id=self.business_id,
                        customer_id=self.customer_id,
                        conversation_id=conversation_id,
                        source_channel="telegram",
                        text=turn["user"],
                    )
                    self.assertEqual(
                        0,
                        db.query(Order).filter_by(
                            business_id=self.business_id,
                            conversation_id=conversation_id,
                        ).count(),
                        f"{dialogue['id']} created an order before checkout verification",
                    )

            conversation_ids = [91000 + index for index in range(1, len(dialogues) + 1)]
            for followup in db.query(ChatbotFollowUp).filter(
                ChatbotFollowUp.conversation_id.in_(conversation_ids)
            ).all():
                db.delete(followup)
            for session in db.query(CustomerCollectionSession).filter(
                CustomerCollectionSession.conversation_id.in_(conversation_ids)
            ).all():
                db.delete(session)
            for product in db.query(Product).filter(
                Product.business_id == self.business_id,
                Product.sku.in_(("EVAL-MODEL-01", "EVAL-MODEL-02", "EVAL-LONA-M-BLACK")),
            ).all():
                db.delete(product)
            db.commit()

    def test_underspecified_purchase_returns_to_shared_assistant_without_opening_checkout(self):
        for conversation_id, text in (
            (98001, "Tôi muốn mua hàng"),
            (98002, "Lấy giúp mình 2 cái"),
            (98003, "I want to buy something"),
            (98004, "I'll take two, please"),
        ):
            with Session(self.engine) as db:
                result = advance_customer_collection(
                    db,
                    business_id=self.business_id,
                    customer_id=self.customer_id,
                    conversation_id=conversation_id,
                    source_channel="telegram",
                    text=text,
                )
                self.assertIsNone(result)
                self.assertEqual(
                    0,
                    db.query(CustomerCollectionSession).filter_by(
                        business_id=self.business_id,
                        conversation_id=conversation_id,
                    ).count(),
                )
                self.assertEqual(
                    0,
                    db.query(Order).filter_by(
                        business_id=self.business_id,
                        conversation_id=conversation_id,
                    ).count(),
                )

    def test_stock_question_stays_out_of_checkout_flow(self):
        with Session(self.engine) as db:
            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=54,
                source_channel="instagram",
                text="tôi muốn mua 20 cái bin bạn có không",
            )

            # Availability questions stay in the assistant route; a stock
            # question must never start or mutate a checkout quote.
            self.assertIsNone(result)
            self.assertEqual(
                0,
                db.query(CustomerCollectionSession).filter_by(conversation_id=54).count(),
            )
            self.assertEqual(
                0,
                db.query(Order).filter_by(conversation_id=54).count(),
            )

    def test_product_model_number_in_stock_question_never_starts_checkout(self):
        with Session(self.engine) as db:
            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=542,
                source_channel="shopee",
                text="Shop ơi, mẫu 1.8 lít Serum còn hàng không ạ?",
            )

            self.assertIsNone(result)
            self.assertEqual(
                0,
                db.query(CustomerCollectionSession).filter_by(conversation_id=542).count(),
            )
            self.assertEqual(0, db.query(Order).filter_by(conversation_id=542).count())

    def test_stock_question_without_quantity_does_not_cancel_pending_quote(self):
        with Session(self.engine) as db:
            quote = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=541,
                source_channel="instagram",
                text="Mình muốn mua Serum",
            )
            self.assertEqual("order_confirmation", quote.current_field)

            result = advance_customer_collection(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=541,
                source_channel="instagram",
                text="Serum còn hàng không ạ?",
            )

            self.assertIsNone(result)
            session = db.query(CustomerCollectionSession).filter_by(conversation_id=541).one()
            self.assertEqual("pending", session.status)
            self.assertEqual("order_confirmation", session.current_field)
            self.assertEqual(
                0,
                db.query(Order).filter_by(conversation_id=541).count(),
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
            self.assertEqual([], notifications)

            # Repeated provider delivery after the completed session must not
            # create a duplicate draft order.
            advance_customer_collection(db, business_id=self.business_id, customer_id=checkout_customer.id, conversation_id=89, source_channel="telegram", text="COD")
            self.assertEqual(1, db.query(Order).filter_by(conversation_id=89).count())
            self.assertEqual(0, db.query(Notification).filter_by(
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

    def test_english_quote_keeps_language_and_replaces_product_on_correction(self):
        with Session(self.engine) as db:
            customer = Customer(
                business_id=self.business_id,
                channel="telegram",
                external_user_id="english-corrected-quote-user",
            )
            appliance = Product(
                business_id=self.business_id,
                sku="HOME-EN-01",
                name="Điện gia dụng mẫu 01",
                price=Decimal("349000"),
                stock_quantity=230,
                metadata_={"display_names": {"en": "Household appliance model 01"}},
                status="active",
            )
            distractor = Product(
                business_id=self.business_id,
                sku="SPORT-EN-01",
                name="Thể thao mẫu 01",
                price=Decimal("89000"),
                stock_quantity=450,
                metadata_={"keywords": ["how much"]},
                status="active",
            )
            db.add_all([customer, appliance, distractor])
            db.flush()
            customer_id = customer.id
            conversation_id = 910_001
            try:
                quote = advance_customer_collection(
                    db,
                    business_id=self.business_id,
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    source_channel="telegram",
                    text="How much would it cost to buy 10 units of the Điện gia dụng mẫu 01?",
                )
                self.assertEqual("order_confirmation", quote.current_field)
                self.assertIn("Household appliance model 01", quote.prompt)
                self.assertIn("₫3,490,000", quote.prompt)
                self.assertNotIn("Bạn muốn", quote.prompt)

                corrected = advance_customer_collection(
                    db,
                    business_id=self.business_id,
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    source_channel="telegram",
                    text="no 10 điện gia dụng",
                )
                self.assertEqual("order_confirmation", corrected.current_field)
                self.assertIn("Household appliance model 01", corrected.prompt)
                self.assertNotIn("Thể thao mẫu 01", corrected.prompt)
                self.assertNotIn("Bạn muốn", corrected.prompt)

                approved = advance_customer_collection(
                    db,
                    business_id=self.business_id,
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    source_channel="telegram",
                    text="yes",
                )
                self.assertEqual("name", approved.current_field)
                self.assertIn("What name", approved.prompt)
                self.assertNotIn("xin", approved.prompt)
            finally:
                db.query(CustomerCollectionSession).filter_by(conversation_id=conversation_id).delete(synchronize_session=False)
                db.delete(appliance)
                db.delete(distractor)
                db.delete(customer)
                db.commit()

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

    def test_quote_only_quantity_correction_keeps_previous_product_without_order(self):
        with Session(self.engine) as db:
            orders_before = db.query(Order).filter(Order.business_id == self.business_id).count()
            db.add(Message(
                conversation_id=58111, channel="shopee", direction="inbound",
                content="Nếu lấy 2 Serum Vitamin C Lunari thì tổng bao nhiêu? Chỉ hỏi giá, chưa đặt hàng.",
            ))
            db.commit()
            first = advance_customer_collection(
                db, business_id=self.business_id, customer_id=self.customer_id,
                conversation_id=58111, source_channel="shopee",
                text="Nếu lấy 2 Serum Vitamin C Lunari thì tổng bao nhiêu? Chỉ hỏi giá, chưa đặt hàng.",
            )
            self.assertIn("840.000 đồng", first.prompt)
            self.assertEqual("catalog_answer", first.status)

            revised = advance_customer_collection(
                db, business_id=self.business_id, customer_id=self.customer_id,
                conversation_id=58111, source_channel="shopee",
                text="Đổi thành 3 chai thì tổng tiền bao nhiêu? Vẫn chỉ hỏi giá, chưa đặt hàng.",
            )
            self.assertIsNotNone(revised)
            self.assertIn("1.260.000 đồng", revised.prompt)
            self.assertEqual("catalog_answer", revised.status)
            self.assertEqual(orders_before, db.query(Order).filter(Order.business_id == self.business_id).count())

            explicit = advance_customer_collection(
                db, business_id=self.business_id, customer_id=self.customer_id,
                conversation_id=58111, source_channel="shopee",
                text="Ý mình là 3 Serum Vitamin C Lunari, tính tổng giúp mình, không tạo đơn.",
            )
            self.assertIsNotNone(explicit)
            self.assertIn("1.260.000 đồng", explicit.prompt)
            self.assertEqual("catalog_answer", explicit.status)
            self.assertEqual(orders_before, db.query(Order).filter(Order.business_id == self.business_id).count())

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
