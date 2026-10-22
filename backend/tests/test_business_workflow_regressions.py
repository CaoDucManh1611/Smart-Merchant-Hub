from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.appointments import AppointmentUpdate, _ensure_no_conflict, update_appointment
from app.api.commercial import ProjectUpdate, QuoteLine, QuoteUpdate, update_project, update_quote
from app.database.bases import TenantBase
from app.models.customer import Customer
from app.models.industry_modules import Appointment, AppointmentService, CommercialProject, CommercialQuote
from app.tenancy.context import TenantContext


@pytest.fixture
def business_db(monkeypatch):
    monkeypatch.setattr("app.api.appointments.emit_workflow_event", lambda *a, **k: None)
    monkeypatch.setattr("app.api.commercial.emit_workflow_event", lambda *a, **k: None)
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    with Session(engine) as db:
        customer = Customer(business_id=1, channel="web", external_user_id="business-regression")
        service = AppointmentService(business_id=1, name="Consult", duration_minutes=60, price=Decimal("100"))
        db.add_all([customer, service])
        db.flush()
        db.add_all([
            CommercialQuote(business_id=1, customer_id=customer.id, quote_number="Q-REG", title="Quote", items=[{"name": "Old", "quantity": "1", "unit_price": "100", "total": "100"}], subtotal=Decimal("100"), tax_rate=Decimal("0"), tax_amount=Decimal("0"), total_amount=Decimal("100")),
            CommercialProject(business_id=1, customer_id=customer.id, title="Project", budget=Decimal("100"), starts_on=date(2030, 1, 10), due_on=date(2030, 1, 20)),
            Appointment(business_id=1, customer_id=customer.id, service_id=service.id, assigned_user_id=44, starts_at=datetime(2030, 1, 10, 2), ends_at=datetime(2030, 1, 10, 3), status="scheduled", reminder_minutes_before=0),
        ])
        db.commit()
        yield db, TenantContext(1, "test")
    engine.dispose()


def test_quote_item_update_persists_lines_and_recomputes_tax(business_db):
    db, tenant = business_db
    quote = db.query(CommercialQuote).one()
    updated = update_quote(quote.id, QuoteUpdate(items=[QuoteLine(name="New", quantity=2, unit_price=Decimal("12.50"))], tax_rate=Decimal("10")), db, tenant)
    db.expire_all()
    assert db.get(CommercialQuote, quote.id).items == updated["items"]
    assert updated["items"][0]["name"] == "New"
    assert updated["subtotal"] == Decimal("25.00")
    assert updated["tax_amount"] == Decimal("2.50")
    assert updated["total_amount"] == Decimal("27.50")


@pytest.mark.parametrize("entity", ["quote", "project"])
def test_business_title_update_rejects_whitespace_without_persisting(business_db, entity):
    db, tenant = business_db
    if entity == "quote":
        row = db.query(CommercialQuote).one()
        update = lambda: update_quote(row.id, QuoteUpdate(title=" \t "), db, tenant)
    else:
        row = db.query(CommercialProject).one()
        update = lambda: update_project(row.id, ProjectUpdate(title=" \t "), db, db, tenant)
    original = row.title
    with pytest.raises(HTTPException) as error:
        update()
    assert error.value.status_code == 422
    db.expire_all()
    assert row.title == original


def test_project_partial_date_update_validates_existing_other_date(business_db):
    db, tenant = business_db
    project = db.query(CommercialProject).one()
    with pytest.raises(HTTPException) as error:
        update_project(project.id, ProjectUpdate(due_on=date(2030, 1, 9)), db, db, tenant)
    assert error.value.status_code == 422
    assert project.due_on == date(2030, 1, 20)
    assert update_project(project.id, ProjectUpdate(starts_on=None), db, db, tenant)["starts_on"] is None


def test_appointment_timezone_roundtrip_and_conflict_boundaries(business_db):
    db, tenant = business_db
    appointment = db.query(Appointment).one()
    local = datetime(2030, 1, 10, 9, tzinfo=timezone(timedelta(hours=7)))
    updated = update_appointment(appointment.id, AppointmentUpdate(starts_at=local), db, db, tenant)
    assert updated["starts_at"] == local
    assert updated["starts_at"].utcoffset() == timedelta(0)
    assert updated["ends_at"] - updated["starts_at"] == timedelta(hours=1)
    with pytest.raises(HTTPException) as conflict:
        _ensure_no_conflict(db, tenant, datetime(2030, 1, 10, 2, 30), datetime(2030, 1, 10, 3, 30), 44)
    assert conflict.value.status_code == 409
    _ensure_no_conflict(db, tenant, datetime(2030, 1, 10, 3), datetime(2030, 1, 10, 4), 44)
    _ensure_no_conflict(db, TenantContext(2, "test"), datetime(2030, 1, 10, 2), datetime(2030, 1, 10, 3), 44)


@pytest.mark.parametrize("status", ["completed", "cancelled", "no_show"])
def test_terminal_appointments_cannot_reopen_or_reschedule(business_db, status):
    db, tenant = business_db
    appointment = db.query(Appointment).one()
    update_appointment(appointment.id, AppointmentUpdate(status=status), db, db, tenant)
    for payload in [AppointmentUpdate(status="scheduled"), AppointmentUpdate(starts_at=datetime(2030, 1, 11, 2))]:
        with pytest.raises(HTTPException) as error:
            update_appointment(appointment.id, payload, db, db, tenant)
        assert error.value.status_code == 409
