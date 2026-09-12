"""Regression tests for the final CRM completion gaps."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.passwords import hash_password
from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business, ServicePlan, Subscription, User
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.customer_collection import CustomerCollectionSession, CustomerVerificationChallenge
from app.models.audit_log import AuditLog
from app.models.message import Message
from app.models.saas import SaaSUsage
from app.models.sales import Order, OrderItem, Product
from app.services.auto_reply_service import estimate_ai_cost, send_text_reply
from app.services.customer_collection_flow import advance_customer_collection
from app.services.otp_delivery import OtpDeliveryResult
from app.services.order_service import (
    release_expired_draft_reservations,
    reserve_draft_order_inventory,
    transition_sales_order,
)
from app.services.quota_service import quota_period_start, reserve_ai_budget


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Business.metadata.create_all(engine)
    return engine


def _finish_checkout(db, *, business_id, customer_id, conversation_id):
    quote = advance_customer_collection(
        db, business_id=business_id, customer_id=customer_id,
        conversation_id=conversation_id, source_channel="telegram",
        text="Tôi muốn mua 1 Serum",
    )
    assert quote.current_field == "order_confirmation"
    assert advance_customer_collection(
        db, business_id=business_id, customer_id=customer_id,
        conversation_id=conversation_id, source_channel="telegram",
        text="Đồng ý đặt hàng",
    ).current_field == "name"
    for value in ("Nguyễn Mai", "0912345678", "mai@example.com", "12 Nguyễn Huệ, Quận 1", "COD"):
        result = advance_customer_collection(
            db, business_id=business_id, customer_id=customer_id,
            conversation_id=conversation_id, source_channel="telegram", text=value,
        )
    return result


def test_checkout_creates_draft_then_requires_hashed_otp_before_confirmation():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="OTP Shop", slug="otp-shop")
        db.add(business)
        db.flush()
        customer = Customer(business_id=business.id, channel="telegram", external_user_id="otp-user")
        db.add(customer)
        db.flush()
        db.add(Product(business_id=business.id, sku="SERUM-OTP", name="Serum", price=Decimal("200000"), stock_quantity=5, status="active"))
        conversation = Conversation(business_id=business.id, customer_id=customer.id, channel="telegram")
        db.add(conversation)
        db.flush()

        with patch("app.services.customer_collection_flow.generate_verification_code", return_value="123456"):
            completed = _finish_checkout(db, business_id=business.id, customer_id=customer.id, conversation_id=conversation.id)

        assert completed.completed is True
        order = db.query(Order).filter_by(conversation_id=conversation.id).one()
        assert order.status == "draft"
        assert order.metadata_["contact_verification_pending"] is True
        challenges = db.query(CustomerVerificationChallenge).filter_by(customer_id=customer.id).all()
        assert len(challenges) == 2
        assert all(challenge.code_hash != "123456" for challenge in challenges)
        assert all(challenge.status in {"queued", "sent"} for challenge in challenges)

        blocked = advance_customer_collection(
            db, business_id=business.id, customer_id=customer.id,
            conversation_id=conversation.id, source_channel="telegram", text="Xác nhận",
        )
        assert "OTP" in blocked.prompt
        assert order.metadata_["contact_verification_pending"] is True

        verified = advance_customer_collection(
            db, business_id=business.id, customer_id=customer.id,
            conversation_id=conversation.id, source_channel="telegram", text="123456",
        )
        assert "email" in verified.prompt.lower()
        verified = advance_customer_collection(
            db, business_id=business.id, customer_id=customer.id,
            conversation_id=conversation.id, source_channel="telegram", text="123456",
        )
        assert "xác thực" in verified.prompt.lower()
        assert order.metadata_["contact_verification_pending"] is False
        assert challenges[0].status == "verified"

        confirmed = advance_customer_collection(
            db, business_id=business.id, customer_id=customer.id,
            conversation_id=conversation.id, source_channel="telegram", text="Xác nhận",
        )
        assert "xác nhận đơn nháp" in confirmed.prompt.lower()
        db.refresh(order)
        assert order.status == "draft"
        assert order.metadata_["customer_confirmed"] is True


def test_smtp_checkout_sends_only_email_otp_and_reports_the_channel():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="Email OTP Shop", slug="email-otp-shop")
        db.add(business)
        db.flush()
        customer = Customer(business_id=business.id, channel="telegram", external_user_id="email-otp-user")
        db.add(customer)
        db.flush()
        db.add(Product(
            business_id=business.id,
            sku="SERUM-EMAIL",
            name="Serum",
            price=Decimal("200000"),
            stock_quantity=5,
            status="active",
        ))
        conversation = Conversation(business_id=business.id, customer_id=customer.id, channel="telegram")
        db.add(conversation)
        db.flush()

        with patch("app.services.customer_collection_flow.settings.OTP_DELIVERY_MODE", "smtp"), \
             patch("app.services.customer_collection_flow.generate_verification_code", return_value="123456"), \
             patch(
                 "app.services.customer_collection_flow.deliver_otp",
                 return_value=OtpDeliveryResult(provider="smtp", delivered=True),
             ) as deliver:
            completed = _finish_checkout(
                db,
                business_id=business.id,
                customer_id=customer.id,
                conversation_id=conversation.id,
            )

        assert completed.prompt.find("email") >= 0
        challenges = db.query(CustomerVerificationChallenge).filter_by(customer_id=customer.id).all()
        assert len(challenges) == 1
        assert challenges[0].channel == "email"
        assert challenges[0].status == "sent"
        deliver.assert_called_once()
        assert deliver.call_args.kwargs["channel"] == "email"


def test_otp_pending_checkout_can_be_cancelled_and_releases_the_draft_hold():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="Cancel OTP Shop", slug="cancel-otp-shop")
        db.add(business)
        db.flush()
        customer = Customer(business_id=business.id, channel="telegram", external_user_id="cancel-user")
        db.add(customer)
        db.flush()
        product = Product(
            business_id=business.id,
            sku="SERUM-CANCEL",
            name="Serum",
            price=Decimal("200000"),
            stock_quantity=5,
            status="active",
        )
        db.add(product)
        conversation = Conversation(business_id=business.id, customer_id=customer.id, channel="telegram")
        db.add(conversation)
        db.flush()

        with patch("app.services.customer_collection_flow.generate_verification_code", return_value="123456"):
            completed = _finish_checkout(
                db,
                business_id=business.id,
                customer_id=customer.id,
                conversation_id=conversation.id,
            )

        order = db.query(Order).filter_by(conversation_id=conversation.id).one()
        assert completed.draft_order_id == order.id
        assert order.status == "draft"
        assert product.reserved_quantity == 1

        cancelled = advance_customer_collection(
            db,
            business_id=business.id,
            customer_id=customer.id,
            conversation_id=conversation.id,
            source_channel="telegram",
            text="xoá",
        )

        assert cancelled is not None
        assert "hủy đơn nháp" in cancelled.prompt.lower()
        db.refresh(order)
        db.refresh(product)
        assert order.status == "cancelled"
        assert order.reserved_quantity == 0
        assert product.reserved_quantity == 0
        session = db.query(CustomerCollectionSession).filter_by(id=completed.session_id).one()
        assert session.status == "abandoned"
        assert session.collected_fields["otp_pending"] is False
        challenges = db.query(CustomerVerificationChallenge).filter_by(customer_id=customer.id).all()
        assert challenges
        assert all(challenge.status == "expired" for challenge in challenges)


def test_new_purchase_does_not_resume_the_old_otp_session():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="Fresh Purchase Shop", slug="fresh-purchase-shop")
        db.add(business)
        db.flush()
        customer = Customer(business_id=business.id, channel="telegram", external_user_id="fresh-user")
        db.add(customer)
        db.flush()
        old_product = Product(
            business_id=business.id,
            sku="SERUM-OLD",
            name="Serum",
            price=Decimal("200000"),
            stock_quantity=5,
            status="active",
        )
        new_product = Product(
            business_id=business.id,
            sku="BIN-NEW",
            name="Bin",
            price=Decimal("100000"),
            stock_quantity=5,
            status="active",
        )
        db.add_all([old_product, new_product])
        conversation = Conversation(business_id=business.id, customer_id=customer.id, channel="telegram")
        db.add(conversation)
        db.flush()

        with patch("app.services.customer_collection_flow.generate_verification_code", return_value="123456"):
            _finish_checkout(
                db,
                business_id=business.id,
                customer_id=customer.id,
                conversation_id=conversation.id,
            )

        old_order = db.query(Order).filter_by(conversation_id=conversation.id).one()
        fresh = advance_customer_collection(
            db,
            business_id=business.id,
            customer_id=customer.id,
            conversation_id=conversation.id,
            source_channel="telegram",
            text="mình muốn mua 1 bin",
        )

        assert fresh is not None
        assert "otp" not in fresh.prompt.lower()
        assert "bin" in fresh.prompt.lower()
        db.refresh(old_order)
        assert old_order.status == "cancelled"


def test_generic_new_purchase_returns_to_catalogue_after_old_otp_is_cancelled():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="Catalogue Reset Shop", slug="catalogue-reset-shop")
        db.add(business)
        db.flush()
        customer = Customer(business_id=business.id, channel="telegram", external_user_id="catalogue-user")
        db.add(customer)
        db.flush()
        db.add(Product(
            business_id=business.id,
            sku="SERUM-RESET",
            name="Serum",
            price=Decimal("200000"),
            stock_quantity=5,
            status="active",
        ))
        conversation = Conversation(business_id=business.id, customer_id=customer.id, channel="telegram")
        db.add(conversation)
        db.flush()

        with patch("app.services.customer_collection_flow.generate_verification_code", return_value="123456"):
            _finish_checkout(
                db,
                business_id=business.id,
                customer_id=customer.id,
                conversation_id=conversation.id,
            )

        result = advance_customer_collection(
            db,
            business_id=business.id,
            customer_id=customer.id,
            conversation_id=conversation.id,
            source_channel="telegram",
            text="mình muốn mua hàng",
        )

        # ``None`` deliberately hands the fresh catalogue request back to
        # the normal RAG responder instead of sending the old OTP prompt.
        assert result is None
        old_order = db.query(Order).filter_by(conversation_id=conversation.id).one()
        assert old_order.status == "cancelled"


def test_quality_dashboard_exposes_usage_provider_ai_and_sla_sections():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="Dashboard Shop", slug="dashboard-shop")
        db.add(business)
        db.flush()
        owner = User(business_id=business.id, full_name="Owner", email="owner@dashboard", password_hash=hash_password("password"), role="owner")
        db.add(owner)
        plan = ServicePlan(
            code="dashboard-plan",
            name="Dashboard plan",
            max_users=10,
            max_channels=4,
            max_documents=20,
            max_rag_chunks=500,
            max_ai_calls=100,
            max_ai_cost=Decimal("50"),
        )
        db.add(plan)
        db.flush()
        db.add(Subscription(business_id=business.id, plan_id=plan.id, status="active"))
        db.add(SaaSUsage(
            business_id=business.id,
            resource="ai_calls",
            period_start=quota_period_start(),
            used=Decimal("7"),
        ))
        db.commit()
        business_id = business.id

    def override_get_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get("/api/reports/quality", headers={"X-Business-Id": str(business_id)})
        assert response.status_code == 200, response.text
        body = response.json()
        assert {"usage", "provider", "ai", "sla"}.issubset(body)
        assert {"calls", "cost"}.issubset(body["ai"])
        assert {"failed_events", "circuits"}.issubset(body["provider"])
        assert body["ai"]["calls"] == 7
        assert body["usage"]["ai_calls"] == {"used": 7, "limit": 100, "remaining": 93}
    finally:
        app.dependency_overrides.clear()


def test_ai_cost_estimate_is_deterministic_and_accounts_for_configured_output_budget():
    short = estimate_ai_cost([{"role": "user", "content": "giá serum"}])
    long = estimate_ai_cost([{"role": "user", "content": "giá serum"}], answer="x" * 4096)
    assert short > 0
    # A concrete answer can never reduce the conservative preflight estimate.
    assert long >= short


def test_ai_budget_is_reserved_once_per_request_key():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="AI Budget Shop", slug="ai-budget-shop")
        db.add(business)
        db.flush()
        plan = ServicePlan(
            code="ai-budget-plan",
            name="AI budget plan",
            max_users=5,
            max_channels=2,
            max_documents=5,
            max_rag_chunks=100,
            max_ai_calls=2,
            max_ai_cost=Decimal("50"),
        )
        db.add(plan)
        db.flush()
        db.add(Subscription(business_id=business.id, plan_id=plan.id, status="active"))
        db.commit()

        messages = [{"role": "user", "content": "giá sản phẩm"}]
        first = reserve_ai_budget(
            db,
            business.id,
            messages,
            idempotency_key="chat:test-request-1",
        )
        second = reserve_ai_budget(
            db,
            business.id,
            messages,
            idempotency_key="chat:test-request-1",
        )
        db.commit()

        rows = db.query(SaaSUsage).filter(SaaSUsage.business_id == business.id).all()
        usage = {row.resource: Decimal(str(row.used)) for row in rows}
        assert first["calls"].requested == Decimal("1")
        assert first["cost"] > Decimal("0")
        assert second["calls"].requested == Decimal("1")
        assert second["cost"] == first["cost"]
        assert usage["ai_calls"] == Decimal("1")
        assert usage["ai_cost"] == first["cost"]


def test_outbound_auto_reply_key_is_idempotent_across_provider_retries():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="Idempotency Shop", slug="idempotency-shop")
        db.add(business)
        db.flush()
        customer = Customer(
            business_id=business.id,
            channel="telegram",
            external_user_id="retry-user",
        )
        db.add(customer)
        db.flush()
        conversation = Conversation(
            business_id=business.id,
            customer_id=customer.id,
            channel="telegram",
        )
        db.add(conversation)
        db.commit()

        with patch(
            "app.services.auto_reply_service._get_conversation_recipient",
            return_value=("telegram", "retry-user"),
        ), patch(
            "app.services.auto_reply_service._send_channel_reply",
            return_value={"message_id": "provider-1"},
        ) as provider:
            first = send_text_reply(
                db=db,
                conversation_id=conversation.id,
                channel="telegram",
                text="Một phản hồi duy nhất",
                business_id=business.id,
                auto_reply_key="inbound:1:1:1:rag",
            )
            second = send_text_reply(
                db=db,
                conversation_id=conversation.id,
                channel="telegram",
                text="Một phản hồi duy nhất",
                business_id=business.id,
                auto_reply_key="inbound:1:1:1:rag",
            )

        assert first["message_id"] == "provider-1"
        assert second["idempotent"] is True
        assert provider.call_count == 1
        rows = db.query(Message).filter(Message.auto_reply_key == "inbound:1:1:1:rag").all()
        assert len(rows) == 1
        assert rows[0].status == "sent"
        sent_audit = db.query(AuditLog).filter(
            AuditLog.action == "chatbot_auto_reply_sent",
            AuditLog.correlation_id == "inbound:1:1:1:rag",
        ).one()
        assert sent_audit.actor_type == "bot"
        duplicate_audit = db.query(AuditLog).filter(
            AuditLog.action == "chatbot_auto_reply_duplicate",
            AuditLog.correlation_id == "inbound:1:1:1:rag",
        ).one()
        assert duplicate_audit.actor_type == "system"


def test_draft_order_reserves_inventory_and_expiry_releases_it():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="Reservation Shop", slug="reservation-shop")
        db.add(business)
        db.flush()
        customer = Customer(
            business_id=business.id,
            channel="telegram",
            external_user_id="reservation-user",
        )
        product = Product(
            business_id=business.id,
            sku="RESERVE-01",
            name="Reserved Product",
            price=Decimal("100"),
            stock_quantity=5,
            reserved_quantity=0,
            status="active",
        )
        db.add_all([customer, product])
        db.flush()
        order = Order(
            business_id=business.id,
            customer_id=customer.id,
            order_number="RESERVE-ORDER-1",
            status="draft",
            total_amount=Decimal("200"),
        )
        db.add(order)
        db.flush()
        db.add(OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=2,
            unit_price=product.price,
            line_total=Decimal("200"),
            product_name_snapshot=product.name,
            sku_snapshot=product.sku,
        ))
        db.flush()

        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)
        reserve_draft_order_inventory(db, order=order, business_id=business.id, expires_at=expires_at)
        db.commit()
        db.refresh(order)
        db.refresh(product)
        assert order.reserved_quantity == 2
        assert product.reserved_quantity == 2
        assert order.metadata_["reservation_status"] == "held"
        assert order.reservation_expires_at == expires_at

        released = release_expired_draft_reservations(
            db,
            business.id,
            now=expires_at + timedelta(seconds=1),
        )
        db.commit()
        db.refresh(order)
        db.refresh(product)
        assert released == 1
        assert order.reserved_quantity == 0
        assert product.reserved_quantity == 0
        assert order.metadata_["reservation_status"] == "expired"


def test_confirming_a_held_draft_does_not_double_reserve_inventory():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="Held Confirm Shop", slug="held-confirm-shop")
        customer = Customer(
            business=business,
            channel="telegram",
            external_user_id="held-confirm-user",
        )
        product = Product(
            business=business,
            sku="HELD-01",
            name="Held Product",
            price=Decimal("50"),
            stock_quantity=5,
            status="active",
        )
        db.add_all([business, customer, product])
        db.flush()
        order = Order(
            business_id=business.id,
            customer_id=customer.id,
            order_number="HELD-CONFIRM-1",
            status="draft",
            total_amount=Decimal("100"),
        )
        db.add(order)
        db.flush()
        db.add(OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=2,
            unit_price=product.price,
            line_total=Decimal("100"),
            product_name_snapshot=product.name,
            sku_snapshot=product.sku,
        ))
        db.flush()
        reserve_draft_order_inventory(db, order=order, business_id=business.id)
        assert product.reserved_quantity == 2

        transition_sales_order(
            db,
            order_id=order.id,
            to_status="confirmed",
            actor_id=None,
            business_id=business.id,
        )
        db.commit()
        db.refresh(product)
        db.refresh(order)
        assert order.status == "confirmed"
        assert product.reserved_quantity == 2


def test_ai_evaluation_dashboard_reports_handoff_and_duplicate_attempts():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="Evaluation Shop", slug="evaluation-shop")
        db.add(business)
        db.flush()
        customer = Customer(
            business_id=business.id,
            channel="telegram",
            external_user_id="evaluation-user",
        )
        db.add(customer)
        db.flush()
        conversation = Conversation(
            business_id=business.id,
            customer_id=customer.id,
            channel="telegram",
        )
        db.add(conversation)
        db.flush()
        db.add_all([
            Message(
                conversation_id=conversation.id,
                channel="telegram",
                direction="inbound",
                sender_type="customer",
                content="Xin hỗ trợ",
            ),
            Message(
                conversation_id=conversation.id,
                channel="telegram",
                direction="outbound",
                sender_type="bot",
                auto_reply_key="inbound:1:1:1:rag",
                status="sent",
            ),
            AuditLog(
                business_id=business.id,
                action="chatbot_human",
                resource_type="conversation",
                resource_id=str(conversation.id),
            ),
            AuditLog(
                business_id=business.id,
                action="chatbot_auto_reply_duplicate",
                resource_type="conversation",
                resource_id=str(conversation.id),
            ),
        ])
        db.commit()
        business_id = business.id

    def override_get_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get(
            "/api/experiments/evaluation/dashboard?days=30",
            headers={"X-Business-Id": str(business_id)},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert {"handoff", "reliability"}.issubset(body["ai"])
        assert {"count", "rate"}.issubset(body["ai"]["handoff"])
        assert "duplicate_reply_attempts" in body["ai"]["reliability"]
        assert body["ai"]["handoff"]["count"] == 1
        assert body["ai"]["reliability"]["duplicate_reply_attempts"] == 1
    finally:
        app.dependency_overrides.clear()
