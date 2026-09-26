from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import pytest
from fastapi import HTTPException

from app.api.appointments import AppointmentCreate, ServiceCreate, _ensure_no_conflict, create_appointment, create_service
from app.api.commercial import (
    InvoiceCreate,
    InvoicePaymentCreate,
    InvoiceUpdate,
    QuoteCreate,
    QuoteLine,
    QuoteUpdate,
    convert_quote_to_project,
    create_invoice,
    create_quote,
    record_invoice_payment,
    send_invoice_email,
    send_quote_email,
    update_invoice,
    update_quote,
)
from app.database.bases import TenantBase
from app.models.customer import Customer
from app.models.industry_modules import Appointment, CommercialInvoice
from app.models.notification import Notification
from app.models.ticket import Ticket
from app.models.workflow import Workflow, WorkflowRun
from app.models.business_setting import BusinessSetting
from app.tenancy.workspace_modules import SETTING_KEY
from app.services.crm_job_worker import _dispatch_appointment_reminder_job
from app.tenancy.context import TenantContext


def test_appointments_remind_once_and_quote_to_project_to_paid_invoice(monkeypatch):
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    tenant = TenantContext(1, "test")
    try:
        with Session(engine) as db:
            customer = Customer(business_id=1, channel="web", external_user_id="c-1", name="Khách 1", email="customer@example.com")
            db.add(customer)
            db.add(BusinessSetting(business_id=1, key=SETTING_KEY, value='{"business_type":"services","enabled_modules":["appointments"]}'))
            db.add_all([
                Workflow(business_id=1, name="Appointment follow-up", event_type="appointment.created", actions=[{"type": "create_ticket", "title": "Confirm appointment", "priority": "normal"}]),
                Workflow(business_id=1, name="Quote review", event_type="quote.created", actions=[{"type": "create_ticket", "title": "Review quote", "priority": "normal"}]),
            ])
            db.commit()

            service = create_service(ServiceCreate(name="Tư vấn", duration_minutes=45, price=Decimal("100000")), db, tenant)
            appointment = create_appointment(
                AppointmentCreate(
                    customer_id=customer.id,
                    service_id=service.id,
                    starts_at=datetime.now(timezone.utc) + timedelta(hours=2),
                    reminder_minutes_before=60,
                ),
                db=db,
                user_db=db,
                tenant=tenant,
            )
            assert appointment["ends_at"] - appointment["starts_at"] == timedelta(minutes=45)
            assert db.query(Ticket).filter_by(title="Confirm appointment").count() == 1
            appointment_row = db.query(Appointment).filter_by(id=appointment["id"]).one()
            collision = Appointment(
                business_id=1, customer_id=customer.id, service_id=service.id, assigned_user_id=44,
                starts_at=appointment_row.starts_at, ends_at=appointment_row.ends_at, status="confirmed",
                reminder_minutes_before=60,
            )
            db.add(collision)
            db.commit()
            with pytest.raises(HTTPException) as conflict:
                _ensure_no_conflict(db, tenant, appointment_row.starts_at, appointment_row.ends_at, assigned_user_id=44)
            assert conflict.value.status_code == 409
            db.delete(collision)
            db.commit()
            appointment_row.reminder_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
            db.commit()
            reminder = {"appointment_id": appointment_row.id, "reminder_at": appointment_row.reminder_at.isoformat()}
            _dispatch_appointment_reminder_job(db, 1, reminder)
            _dispatch_appointment_reminder_job(db, 1, reminder)
            assert db.query(Notification).filter_by(kind="appointment_reminder").count() == 1

            sent_emails = []
            monkeypatch.setattr(
                "app.services.crm_job_worker.deliver_notification_email",
                lambda **kwargs: sent_emails.append(kwargs) or True,
            )
            email_appointment = create_appointment(
                AppointmentCreate(
                    customer_id=customer.id,
                    service_id=service.id,
                    starts_at=datetime.now(timezone.utc) + timedelta(hours=3),
                    reminder_minutes_before=60,
                    send_customer_reminder=True,
                ),
                db=db,
                user_db=db,
                tenant=tenant,
            )
            email_appointment_row = db.query(Appointment).filter_by(id=email_appointment["id"]).one()
            email_appointment_row.reminder_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
            db.commit()
            _dispatch_appointment_reminder_job(db, 1, {
                "appointment_id": email_appointment_row.id,
                "reminder_at": email_appointment_row.reminder_at.isoformat(),
            })
            assert sent_emails[-1]["recipient_email"] == "customer@example.com"
            assert "lịch" in sent_emails[-1]["body"].lower()

            quote = create_quote(
                QuoteCreate(
                    customer_id=customer.id,
                    title="Thiết kế website",
                    items=[QuoteLine(name="Thiết kế", quantity=2, unit_price=Decimal("1000000"))],
                    tax_rate=Decimal("10"),
                ),
                db,
                tenant,
            )
            assert quote["subtotal"] == Decimal("2000000.00")
            assert quote["total_amount"] == Decimal("2200000.00")
            assert db.query(Ticket).filter_by(title="Review quote").count() == 1
            assert db.query(WorkflowRun).filter_by(event_type="quote.created", status="completed").count() == 1
            monkeypatch.setattr(
                "app.api.commercial.deliver_notification_email",
                lambda **kwargs: sent_emails.append(kwargs) or True,
            )
            emailed_quote = send_quote_email(quote["id"], db, tenant)
            assert emailed_quote["status"] == "sent"
            assert emailed_quote["email_sent_at"] is not None
            assert sent_emails[-1]["recipient_email"] == "customer@example.com"
            with pytest.raises(HTTPException) as duplicate_quote_email:
                send_quote_email(quote["id"], db, tenant)
            assert duplicate_quote_email.value.status_code == 409
            update_quote(quote["id"], QuoteUpdate(status="accepted"), db, tenant)
            project = convert_quote_to_project(quote["id"], db, tenant)
            assert convert_quote_to_project(quote["id"], db, tenant)["id"] == project["id"]
            invoice = create_invoice(
                InvoiceCreate(
                    customer_id=customer.id,
                    project_id=project["id"],
                    quote_id=quote["id"],
                    description="Đợt thanh toán",
                    total_amount=Decimal("2200000"),
                    status="issued",
                ),
                db,
                tenant,
            )
            emailed_invoice = send_invoice_email(invoice["id"], db, tenant)
            assert emailed_invoice["email_sent_at"] is not None
            assert "Hóa đơn" in sent_emails[-1]["title"]
            record_invoice_payment(invoice["id"], InvoicePaymentCreate(amount=Decimal("1000000")), db, tenant)
            paid = record_invoice_payment(invoice["id"], InvoicePaymentCreate(amount=Decimal("1200000")), db, tenant)
            assert paid["status"] == "paid"
            assert len(paid["payments"]) == 2
            assert db.query(CommercialInvoice).filter_by(id=invoice["id"]).one().paid_amount == Decimal("2200000.00")
            with pytest.raises(HTTPException) as overpayment:
                record_invoice_payment(invoice["id"], InvoicePaymentCreate(amount=Decimal("1")), db, tenant)
            assert overpayment.value.status_code == 422
            with pytest.raises(HTTPException) as void_paid:
                update_invoice(invoice["id"], InvoiceUpdate(status="void"), db, tenant)
            assert void_paid.value.status_code == 409
    finally:
        engine.dispose()
