import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.session import Base
from app.models.business import Business
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.message import Message
from app.models.sales import Order, OrderItem, Product
from app.services.chatbot_agent import execute_chatbot_tool
from app.services.customer_order_service import customer_order_reply


class CustomerOrderActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Customer Order Actions", slug="customer-order-actions")
            db.add(business)
            db.flush()
            customer = Customer(
                business_id=business.id,
                channel="telegram",
                external_user_id="order-actions-customer",
                name="Order Buyer",
                phone="+84901234567",
            )
            other_customer = Customer(
                business_id=business.id,
                channel="telegram",
                external_user_id="other-order-customer",
                name="Other Buyer",
            )
            product = Product(
                business_id=business.id,
                sku="ORDER-ACTION-01",
                name="Order Action Product",
                price=Decimal("100"),
                stock_quantity=50,
            )
            unique_product = Product(
                business_id=business.id,
                sku="UNIQUE-DRAFT-01",
                name="Unique Draft Product",
                price=Decimal("150"),
                stock_quantity=20,
            )
            db.add_all([customer, other_customer, product, unique_product])
            db.flush()
            conversation = Conversation(
                business_id=business.id,
                customer_id=customer.id,
                channel="telegram",
            )
            db.add(conversation)
            db.flush()
            db.add(Message(
                conversation_id=conversation.id,
                channel="telegram",
                direction="inbound",
                sender_type="customer",
                content="Tôi muốn kiểm tra đơn hàng",
            ))

            def add_order(number, status, customer_id=customer.id, paid=Decimal("0"), order_product=product):
                order = Order(
                    business_id=business.id,
                    customer_id=customer_id,
                    conversation_id=conversation.id if customer_id == customer.id else None,
                    order_number=number,
                    status=status,
                    total_amount=order_product.price,
                    paid_amount=paid,
                    payment_status="paid" if paid else "unpaid",
                )
                db.add(order)
                db.flush()
                db.add(OrderItem(
                    order_id=order.id,
                    product_id=order_product.id,
                    quantity=1,
                    unit_price=order_product.price,
                    line_total=order_product.price,
                    product_name_snapshot=order_product.name,
                    sku_snapshot=order_product.sku,
                ))
                return order

            add_order("ORD-DRAFT-1", "draft", order_product=unique_product)
            add_order("ORD-PROCESSING-1", "processing")
            add_order("ORD-DELIVERED-1", "delivered", paid=Decimal("100"))
            add_order("ORD-OTHER-1", "draft", customer_id=other_customer.id)
            db.commit()
            cls.business_id = business.id
            cls.customer_id = customer.id
            cls.conversation_id = conversation.id

    def test_order_lookup_is_scoped_to_conversation_customer(self):
        with Session(self.engine) as db:
            result = execute_chatbot_tool(
                db,
                self.business_id,
                self.conversation_id,
                "xem_don_cua_khach",
                {},
            )

        numbers = {item["order_number"] for item in result["items"]}
        self.assertEqual(3, len(numbers))
        self.assertNotIn("ORD-OTHER-1", numbers)
        self.assertTrue(result["requires_order_identifier"])

    def setUp(self):
        with Session(self.engine) as db:
            db.get(Conversation, self.conversation_id).bot_mode = "auto"
            # Keep the shared fixture deterministic: cancellation tests mutate
            # the draft, while lookup tests need a live draft to exercise the
            # transactional router.
            draft = db.query(Order).filter(Order.order_number == "ORD-DRAFT-1").one()
            draft.status = "draft"
            draft.cancel_reason = None
            db.commit()

    def test_status_lookup_rejects_order_owned_by_another_customer(self):
        with Session(self.engine) as db:
            result = execute_chatbot_tool(
                db,
                self.business_id,
                self.conversation_id,
                "xem_trang_thai_don",
                {"order_number": "ORD-OTHER-1"},
            )

        self.assertEqual({"found": False, "reason": "order_not_found"}, result)

    def test_unpaid_draft_can_be_cancelled_without_staff_takeover(self):
        with Session(self.engine) as db:
            result = execute_chatbot_tool(
                db,
                self.business_id,
                self.conversation_id,
                "yeu_cau_huy_don",
                {"order_number": "ORD-DRAFT-1", "reason": "Khách đổi ý"},
            )
            db.commit()
            order = db.query(Order).filter(Order.order_number == "ORD-DRAFT-1").one()
            conversation = db.get(Conversation, self.conversation_id)

        self.assertTrue(result["accepted"])
        self.assertEqual("self_service", result["mode"])
        self.assertEqual("cancelled", order.status)
        self.assertEqual("auto", conversation.bot_mode)

    def test_processing_cancellation_creates_high_priority_ticket_and_handoffs(self):
        with Session(self.engine) as db:
            result = execute_chatbot_tool(
                db,
                self.business_id,
                self.conversation_id,
                "yeu_cau_huy_don",
                {"order_number": "ORD-PROCESSING-1", "reason": "Không còn nhu cầu"},
            )
            db.commit()
            order = db.query(Order).filter(Order.order_number == "ORD-PROCESSING-1").one()
            conversation = db.get(Conversation, self.conversation_id)

        self.assertTrue(result["accepted"])
        self.assertEqual("staff_review", result["mode"])
        self.assertEqual("processing", order.status)
        self.assertEqual("human", conversation.bot_mode)
        self.assertIsNotNone(result["ticket_id"])

    def test_refund_request_creates_staff_ticket_without_refunding_money(self):
        with Session(self.engine) as db:
            result = execute_chatbot_tool(
                db,
                self.business_id,
                self.conversation_id,
                "yeu_cau_hoan_don",
                {"order_number": "ORD-DELIVERED-1", "reason": "Hàng lỗi"},
            )
            db.commit()
            order = db.query(Order).filter(Order.order_number == "ORD-DELIVERED-1").one()
            conversation = db.get(Conversation, self.conversation_id)

        self.assertTrue(result["accepted"])
        self.assertEqual("staff_review", result["mode"])
        self.assertEqual(Decimal("0.00"), Decimal(order.refunded_amount or 0))
        self.assertEqual("human", conversation.bot_mode)
        self.assertIsNotNone(result["ticket_id"])

    def test_customer_status_reply_asks_for_order_number_when_orders_are_ambiguous(self):
        with Session(self.engine) as db:
            reply = customer_order_reply(
                db,
                self.business_id,
                self.conversation_id,
                "Bạn kiểm tra giúp đơn hàng của tôi",
            )

        self.assertIn("ORD-DRAFT-1", reply)
        self.assertIn("mã đơn", reply)

    def test_customer_status_reply_uses_conversation_customer_for_exact_order(self):
        with Session(self.engine) as db:
            reply = customer_order_reply(
                db,
                self.business_id,
                self.conversation_id,
                "Kiểm tra trạng thái đơn ORD-DRAFT-1",
            )

        self.assertIn("ORD-DRAFT-1", reply)
        self.assertIn("Đơn nháp", reply)

    def test_customer_status_reply_understands_natural_order_list_phrase(self):
        with Session(self.engine) as db:
            reply = customer_order_reply(
                db,
                self.business_id,
                self.conversation_id,
                "Tôi có đơn hàng nào không?",
            )

        self.assertIn("ORD-DRAFT-1", reply)
        self.assertIn("mã đơn", reply)
        self.assertNotIn("chưa tìm thấy", reply.lower())

    def test_customer_draft_lookup_lists_only_draft_orders(self):
        with Session(self.engine) as db:
            reply = customer_order_reply(
                db,
                self.business_id,
                self.conversation_id,
                "Tôi có đơn hàng nháp nào không?",
            )

        self.assertIn("ORD-DRAFT-1", reply)
        self.assertNotIn("ORD-PROCESSING-1", reply)
        self.assertNotIn("ORD-DELIVERED-1", reply)

    def test_cancel_reply_resolves_unique_product_name(self):
        with Session(self.engine) as db:
            reply = customer_order_reply(
                db,
                self.business_id,
                self.conversation_id,
                "Tôi muốn hủy đơn Unique Draft Product",
            )
            db.commit()
            order = db.query(Order).filter(Order.order_number == "ORD-DRAFT-1").one()

        self.assertIn("đã hủy đơn ORD-DRAFT-1", reply)
        self.assertEqual("cancelled", order.status)

    def test_cancel_reply_lists_product_channel_and_status_when_ambiguous(self):
        with Session(self.engine) as db:
            reply = customer_order_reply(
                db,
                self.business_id,
                self.conversation_id,
                "Tôi muốn hủy đơn Telegram",
            )

        self.assertIn("ORD-DRAFT-1", reply)
        self.assertIn("telegram", reply.lower())
        self.assertIn("Unique Draft Product", reply)
        self.assertIn("Đơn nháp", reply)
        self.assertIn("mã đơn, tên món hoặc kênh", reply)

    def test_cancel_reply_uses_customer_safe_message_for_closed_order(self):
        with Session(self.engine) as db:
            order = db.query(Order).filter(Order.order_number == "ORD-DRAFT-1").one()
            order.status = "cancelled"
            db.commit()
            reply = customer_order_reply(
                db,
                self.business_id,
                self.conversation_id,
                "Hủy đơn ORD-DRAFT-1",
            )

        self.assertIn("đã được hủy trước đó", reply)
        self.assertNotIn("order_already_closed", reply)


if __name__ == "__main__":
    unittest.main()
