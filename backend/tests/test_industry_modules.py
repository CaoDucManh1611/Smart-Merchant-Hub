from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import pytest
from fastapi import HTTPException

from app.api.appointments import AppointmentCreate, AppointmentUpdate, ServiceCreate, _ensure_no_conflict, create_appointment, create_service, list_appointments, update_appointment
from app.api.commercial import (
    InvoiceCreate,
    InvoicePaymentCreate,
    InvoiceUpdate,
    ProjectUpdate,
    QuoteCreate,
    QuoteLine,
    QuoteUpdate,
    convert_quote_to_project,
    create_invoice,
    create_quote,
    list_invoices,
    list_projects,
    list_quotes,
    record_invoice_payment,
    send_invoice_email,
    send_quote_email,
    update_invoice,
    update_project,
    update_quote,
)
from app.database.bases import TenantBase
from app.models.customer import Customer
from app.models.industry_modules import (
    Appointment,
    AppointmentService,
    CommercialInvoice,
    CommercialInvoicePayment,
    CommercialProject,
    CommercialQuote,
)
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
            local_start = datetime.now(timezone(timedelta(hours=7))) + timedelta(hours=2)
            appointment = create_appointment(
                AppointmentCreate(
                    customer_id=customer.id,
                    service_id=service.id,
                    starts_at=local_start,
                    reminder_minutes_before=60,
                ),
                db=db,
                user_db=db,
                tenant=tenant,
            )
            assert appointment["starts_at"].utcoffset() == timedelta(0)
            assert appointment["starts_at"].replace(tzinfo=None) == local_start.astimezone(timezone.utc).replace(tzinfo=None)
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
            cancelled = update_appointment(email_appointment_row.id, AppointmentUpdate(status="cancelled"), db, db, tenant)
            assert cancelled["status"] == "cancelled"
            with pytest.raises(HTTPException) as reopened_appointment:
                update_appointment(email_appointment_row.id, AppointmentUpdate(status="confirmed"), db, db, tenant)
            assert reopened_appointment.value.status_code == 409

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
            with pytest.raises(HTTPException) as terminal_quote:
                update_quote(quote["id"], QuoteUpdate(status="rejected"), db, tenant)
            assert terminal_quote.value.status_code == 409
            project = convert_quote_to_project(quote["id"], db, tenant)
            assert convert_quote_to_project(quote["id"], db, tenant)["id"] == project["id"]
            update_project(project["id"], ProjectUpdate(status="completed"), db, db, tenant)
            with pytest.raises(HTTPException) as terminal_project:
                update_project(project["id"], ProjectUpdate(status="active"), db, db, tenant)
            assert terminal_project.value.status_code == 409
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
            with pytest.raises(HTTPException) as invalid_invoice_transition:
                update_invoice(invoice["id"], InvoiceUpdate(status="draft"), db, tenant)
            assert invalid_invoice_transition.value.status_code == 409
            first_payment_payload = InvoicePaymentCreate(amount=Decimal("1000000"), idempotency_key="invoice-pay-first-001")
            first_payment = record_invoice_payment(invoice["id"], first_payment_payload, db, tenant)
            first_payment_replay = record_invoice_payment(invoice["id"], first_payment_payload, db, tenant)
            assert first_payment_replay["paid_amount"] == first_payment["paid_amount"] == Decimal("1000000.00")
            assert len(first_payment_replay["payments"]) == 1
            with pytest.raises(HTTPException) as reused_payment_key:
                record_invoice_payment(invoice["id"], InvoicePaymentCreate(amount=Decimal("500000"), idempotency_key="invoice-pay-first-001"), db, tenant)
            assert reused_payment_key.value.status_code == 409
            paid = record_invoice_payment(invoice["id"], InvoicePaymentCreate(amount=Decimal("1200000"), idempotency_key="invoice-pay-second-002"), db, tenant)
            assert paid["status"] == "paid"
            assert len(paid["payments"]) == 2
            assert db.query(CommercialInvoice).filter_by(id=invoice["id"]).one().paid_amount == Decimal("2200000.00")
            with pytest.raises(HTTPException) as overpayment:
                record_invoice_payment(invoice["id"], InvoicePaymentCreate(amount=Decimal("1"), idempotency_key="invoice-pay-over-003"), db, tenant)
            assert overpayment.value.status_code == 422
            with pytest.raises(HTTPException) as void_paid:
                update_invoice(invoice["id"], InvoiceUpdate(status="void"), db, tenant)
            assert void_paid.value.status_code == 409
    finally:
        engine.dispose()


def test_appointment_and_b2b_reads_and_writes_are_tenant_scoped():
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    one, two = TenantContext(1, "test"), TenantContext(2, "test")
    try:
        with Session(engine) as db:
            customers = [
                Customer(business_id=business_id, channel="web", external_user_id=f"c-{business_id}", name=f"Shop {business_id}")
                for business_id in (1, 2)
            ]
            services = [
                AppointmentService(business_id=business_id, name=f"Service {business_id}", duration_minutes=60, price=Decimal("100"))
                for business_id in (1, 2)
            ]
            db.add_all([*customers, *services])
            db.flush()
            appointments = [
                Appointment(
                    business_id=business_id,
                    customer_id=customers[business_id - 1].id,
                    service_id=services[business_id - 1].id,
                    starts_at=datetime(2030, 1, 1, 9),
                    ends_at=datetime(2030, 1, 1, 10),
                    status="scheduled",
                )
                for business_id in (1, 2)
            ]
            foreign_quote = CommercialQuote(
                business_id=2, customer_id=customers[1].id, quote_number="Q-FOREIGN",
                title="Foreign quote", items=[], subtotal=Decimal("100"), tax_rate=Decimal("0"),
                tax_amount=Decimal("0"), total_amount=Decimal("100"),
            )
            foreign_project = CommercialProject(
                business_id=2, customer_id=customers[1].id, title="Foreign project", budget=Decimal("100"),
            )
            foreign_invoice = CommercialInvoice(
                business_id=2, customer_id=customers[1].id, invoice_number="INV-FOREIGN",
                description="Foreign invoice", total_amount=Decimal("100"), paid_amount=Decimal("0"), status="issued",
            )
            db.add_all([*appointments, foreign_quote, foreign_project, foreign_invoice])
            db.commit()

            assert [row["id"] for row in list_appointments(db, one, None, None, None, 100, 0)["items"]] == [appointments[0].id]
            assert [row["id"] for row in list_appointments(db, two, None, None, None, 100, 0)["items"]] == [appointments[1].id]
            assert list_quotes(db, one, None, 100, 0)["total"] == 0
            assert list_projects(db, one, None, 100, 0)["total"] == 0
            assert list_invoices(db, one, None, 100, 0)["total"] == 0

            with pytest.raises(HTTPException) as quote_access:
                update_quote(foreign_quote.id, QuoteUpdate(title="Cross-shop edit"), db, one)
            with pytest.raises(HTTPException) as project_access:
                update_project(foreign_project.id, ProjectUpdate(title="Cross-shop edit"), db, db, one)
            with pytest.raises(HTTPException) as invoice_access:
                update_invoice(foreign_invoice.id, InvoiceUpdate(description="Cross-shop edit"), db, one)
            with pytest.raises(HTTPException) as payment_access:
                record_invoice_payment(foreign_invoice.id, InvoicePaymentCreate(amount=Decimal("1"), idempotency_key="invoice-pay-foreign-001"), db, one)
            assert [error.value.status_code for error in (quote_access, project_access, invoice_access, payment_access)] == [404] * 4
    finally:
        engine.dispose()
