from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.reports import _parse_date, commerce_report
from app.database.bases import TenantBase
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.industry_modules import Appointment, AppointmentService, CommercialInvoice, CommercialQuote
from app.models.sales import Order
from app.tenancy.context import TenantContext


def test_commerce_report_uses_scoped_records_and_excludes_shopee():
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            customer = Customer(business_id=1, channel="web", external_user_id="c1", name="One")
            other_customer = Customer(business_id=2, channel="web", external_user_id="c2", name="Two")
            db.add_all([customer, other_customer])
            db.flush()
            facebook = Conversation(business_id=1, customer_id=customer.id, channel="facebook", assigned_user_id=10)
            shopee = Conversation(business_id=1, customer_id=customer.id, channel="shopee", assigned_user_id=10)
            other_channel = Conversation(business_id=2, customer_id=other_customer.id, channel="facebook")
            db.add_all([facebook, shopee, other_channel])
            db.flush()
            db.add_all([
                Order(business_id=1, customer_id=customer.id, conversation_id=facebook.id, order_number="FB-1", status="confirmed", total_amount=Decimal("100.00")),
                Order(business_id=1, customer_id=customer.id, conversation_id=facebook.id, order_number="FB-DRAFT", status="draft", total_amount=Decimal("900.00")),
                Order(business_id=1, customer_id=customer.id, conversation_id=shopee.id, order_number="SHOPEE-1", status="paid", total_amount=Decimal("800.00")),
                Order(business_id=2, customer_id=other_customer.id, conversation_id=other_channel.id, order_number="OTHER-1", status="confirmed", total_amount=Decimal("700.00")),
            ])
            service = AppointmentService(business_id=1, name="Consultation", duration_minutes=30, price=Decimal("50.00"))
            quote = CommercialQuote(business_id=1, customer_id=customer.id, quote_number="Q-1", title="Accepted", status="accepted", items=[], subtotal=Decimal("100.00"), tax_rate=Decimal("10"), tax_amount=Decimal("10.00"), total_amount=Decimal("110.00"))
            invoice = CommercialInvoice(business_id=1, customer_id=customer.id, invoice_number="I-1", description="Part paid", total_amount=Decimal("100.00"), paid_amount=Decimal("25.00"), status="issued")
            db.add_all([service, quote, invoice])
            db.flush()
            appointment = Appointment(business_id=1, customer_id=customer.id, service_id=service.id, assigned_user_id=10, starts_at=datetime(2030, 1, 2, 9), ends_at=datetime(2030, 1, 2, 9, 30), status="scheduled")
            db.add(appointment)
            db.commit()

            result = commerce_report(db, TenantContext(1, "test"), None, None, None, None, None)
            assert result["orders"]["count"] == 2
            assert result["orders"]["recognized_revenue"] == Decimal("100.00")
            assert result["appointments"]["count"] == 1
            assert result["quotes"]["accepted_value"] == Decimal("110.00")
            assert result["invoices"]["outstanding"] == Decimal("75.00")
            assert {item["label"] for item in result["source_records"] if item["kind"] == "order"} == {"FB-1", "FB-DRAFT"}
            assert "SHOPEE-1" not in {item["label"] for item in result["source_records"]}

            filtered = commerce_report(db, TenantContext(1, "test"), None, None, "facebook", None, 10)
            assert filtered["orders"]["count"] == 2
            assert filtered["appointments"]["count"] == 1
            assert commerce_report(db, TenantContext(2, "test"), None, None, None, None, None)["orders"]["recognized_revenue"] == Decimal("700.00")
    finally:
        engine.dispose()


def test_report_date_filter_normalizes_offsets_to_utc():
    assert _parse_date("2030-01-01T00:00:00+07:00", "start_at") == datetime(2029, 12, 31, 17)
