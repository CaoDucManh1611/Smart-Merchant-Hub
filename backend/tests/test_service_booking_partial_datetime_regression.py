"""Keep evidenced appointment fragments without inventing contact or approval."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from test_business_request import setup
from test_service_booking_dialogue_regression import (
    SERVICE_NAMES, assert_no_remote_or_handoff, assert_no_transactions,
    inventory_snapshot, offline_service_dependencies, service_shop,
)
from app.models.customer_collection import CustomerCollectionSession, CustomerContact
from app.models.message import Message
from app.services.business_request import advance_business_request
from app.services.conversation_graph import graph_reply
from app.services.customer_collection import contact_hash, decrypt_contact, encrypt_contact
from app.services.customer_collection_flow import _extract_value
from app.services.product_resolver import normalize_product_text


NAME = "Ngô Long Thiên"
INVALID_PHONE = "032372383"
VALID_PHONE = "0323723830"
DATE = "27/11/2026"
EXPECTED = "2026-11-27T12:30:00+07:00"


class BookingClock(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 25, 10, 0, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)


@pytest.fixture
def booking_shop(service_shop, monkeypatch):
    # Exact user dates remain future independently of the calendar test date.
    monkeypatch.setattr("app.services.business_request.datetime", BookingClock)
    monkeypatch.setattr("app.services.conversation_graph.datetime", BookingClock)
    return service_shop


def turn(db, conversation, query):
    index = db.query(Message).count()
    db.add(Message(
        conversation_id=conversation.id, channel=conversation.channel,
        direction="inbound", sender_type="customer", content=query,
    ))
    db.commit()
    reply = graph_reply(db, business_id=1, conversation=conversation, query=query,
                        job_key=f"partial-service-{index}")
    assert reply is not None
    db.add(Message(
        conversation_id=conversation.id, channel=conversation.channel,
        direction="outbound", sender_type="bot", content=reply.prompt,
        metadata_=reply.metadata or {},
    ))
    db.commit()
    return reply


def start(booking_shop):
    db, conversation, services, products = booking_shop
    reply = turn(db, conversation, f"tôi muốn đặt lịch hẹn {SERVICE_NAMES[1]}")
    session = db.query(CustomerCollectionSession).one()
    assert session.collected_fields["offering_ref"] == f"service:{services[1].id}"
    assert services[1].name in reply.prompt
    return db, conversation, session


def values(db, session):
    db.refresh(session)
    return session.collected_fields.get("values", {})


def seed_contacts(db, conversation):
    reply = turn(db, conversation, f"{NAME}, {VALID_PHONE}")
    assert "trục trặc" not in reply.prompt


def assert_only_pending(db, session, before_inventory):
    db.refresh(session)
    assert session.status in {"pending", "partial"}
    assert session.collected_fields.get("phase") in {"collecting", "review"}
    assert_no_transactions(db, before_inventory)


def test_exact_user_split_sequence_keeps_name_and_date_but_rejects_short_phone(
    booking_shop, offline_service_dependencies,
):
    db, conversation, services, _ = booking_shop
    before = inventory_snapshot(db)
    assert turn(db, conversation, "xin chào").status == "greeting"
    assert services[1].name in turn(db, conversation, "bạn đang có dịch vụ gì").prompt
    db, conversation, session = start(booking_shop)

    invalid_reply = turn(db, conversation, f"{NAME} , {INVALID_PHONE} , {DATE}")
    collected = values(db, session)
    assert collected.get("name") == NAME
    assert "phone" not in collected and "starts_at" not in collected
    assert db.query(CustomerContact).filter_by(kind="phone").count() == 0
    folded = normalize_product_text(invalid_reply.prompt)
    assert any(term in folded for term in ("so lien he", "so dien thoai"))
    assert any(term in folded for term in ("hop le", "10 chu so", "kiem tra", "chinh xac"))

    turn(db, conversation, "12h30")
    assert values(db, session).get("starts_at") == EXPECTED
    repeated = turn(db, conversation, DATE)
    assert values(db, session).get("starts_at") == EXPECTED
    assert "Họ tên" not in repeated.prompt and "ngày nào" not in repeated.prompt
    turn(db, conversation, "Chuyển khoản")
    collected = values(db, session)
    assert collected["name"] == NAME and collected["starts_at"] == EXPECTED
    assert collected["payment_method"] == "bank_transfer"
    assert "phone" not in collected
    assert session.collected_fields["phase"] == "collecting"
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)


def test_valid_phone_correction_preserves_collected_date_time_and_payment(
    booking_shop, offline_service_dependencies,
):
    db, conversation, session = start(booking_shop)
    before = inventory_snapshot(db)
    for query in [f"{NAME}, {INVALID_PHONE}, {DATE}", "12h30", "Chuyển khoản"]:
        turn(db, conversation, query)
    reply = turn(db, conversation, VALID_PHONE)
    collected = values(db, session)
    assert collected["name"] == NAME and collected["starts_at"] == EXPECTED
    assert collected["phone"] == "đã cung cấp"
    assert collected["payment_method"] == "bank_transfer"
    contact = db.query(CustomerContact).filter_by(kind="phone").one()
    assert decrypt_contact("phone", contact.value_encrypted) == "+84323723830"
    assert session.collected_fields["phase"] == "review"
    assert all(term in reply.prompt for term in (NAME, DATE, "12:30", "Chuyển khoản", "xác nhận gửi"))
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)


@pytest.mark.parametrize("fragments", [
    [DATE, "12h30"], ["12h30", DATE], [DATE, "12:30"], ["12:30", DATE],
])
def test_date_and_time_combine_in_either_order_without_reasking_previous_fields(
    booking_shop, offline_service_dependencies, fragments,
):
    db, conversation, session = start(booking_shop)
    before = inventory_snapshot(db)
    seed_contacts(db, conversation)
    first_reply = turn(db, conversation, fragments[0])
    assert "starts_at" not in values(db, session)
    assert "Họ tên" not in first_reply.prompt and "Số liên hệ" not in first_reply.prompt
    last_reply = turn(db, conversation, fragments[1])
    assert values(db, session)["starts_at"] == EXPECTED
    assert "Họ tên" not in last_reply.prompt and "Thời gian mong muốn" not in last_reply.prompt
    assert session.collected_fields["phase"] == "collecting"
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)


@pytest.mark.parametrize("correction,expected", [
    ("28/11/2026", "2026-11-28T12:30:00+07:00"),
    ("13h45", "2026-11-27T13:45:00+07:00"),
])
def test_correcting_one_calendar_component_preserves_other_component_and_contact(
    booking_shop, offline_service_dependencies, correction, expected,
):
    db, conversation, session = start(booking_shop)
    before = inventory_snapshot(db)
    seed_contacts(db, conversation)
    turn(db, conversation, f"{DATE} 12h30")
    assert values(db, session)["starts_at"] == EXPECTED
    turn(db, conversation, correction)
    collected = values(db, session)
    assert collected["starts_at"] == expected
    assert collected["name"] == NAME and collected["phone"] == "đã cung cấp"
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)


@pytest.mark.parametrize("query", [
    "27/11/2026 hoặc 28/11/2026 lúc 12h30",
    "27/11/2026 lúc 12h30 hoặc 13h45",
])
def test_ambiguous_calendar_choices_do_not_silently_select_first(
    booking_shop, offline_service_dependencies, query,
):
    db, conversation, session = start(booking_shop)
    before = inventory_snapshot(db)
    seed_contacts(db, conversation)
    reply = turn(db, conversation, query)
    assert "starts_at" not in values(db, session)
    assert any(term in normalize_product_text(reply.prompt) for term in ("chon", "xac nhan", "ngay", "gio", "thoi gian"))
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)


def test_short_phone_is_invalid_before_country_code_normalization():
    assert _extract_value("phone", INVALID_PHONE) is None
    assert _extract_value("phone", VALID_PHONE) == "+84323723830"


def test_service_contact_labels_and_cancellation_do_not_replace_recipient_name():
    from app.services.business_request import pending_contact_action
    existing = {'offering_ref': 'service:1', 'field_definitions': [
        {'key': 'name', 'type': 'text'}, {'key': 'phone', 'type': 'phone'},
        {'key': 'starts_at', 'type': 'datetime'},
    ], 'values': {'name': NAME}}
    correction = pending_contact_action(f'Số liên hệ: {VALID_PHONE}', existing)
    assert correction['fields']['phone']['value'] == VALID_PHONE
    assert 'name' not in correction['fields']
    assert pending_contact_action('Dừng yêu cầu này', existing) is None


def test_prior_stored_contact_cannot_fill_current_invalid_phone_without_evidence(
    booking_shop, offline_service_dependencies,
):
    db, conversation, session = start(booking_shop)
    old = "+84901111222"
    db.add(CustomerContact(
        business_id=1, customer_id=conversation.customer_id, kind="phone",
        value_encrypted=encrypt_contact("phone", old), value_hash=contact_hash("phone", old),
        masked_value="******1222", is_primary=True, source="manual",
    ))
    db.commit()
    before = inventory_snapshot(db)
    for query in [f"{NAME}, {INVALID_PHONE}, {DATE}", "12h30", "Chuyển khoản"]:
        turn(db, conversation, query)
    assert values(db, session).get("name") == NAME
    assert values(db, session).get("starts_at") == EXPECTED
    assert "phone" not in values(db, session)
    assert not session.collected_fields.get("encrypted_phone")
    assert db.query(CustomerContact).filter_by(kind="phone").count() == 1
    assert session.collected_fields["phase"] == "collecting"
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)


@pytest.mark.parametrize("query,value,proof", [
    ("27/11/2026 12h30", "2026-11-27T18:30:00+07:00", "27/11/2026 12h30"),
    ("27/11/2026 hoặc 28/11/2026 12h30", EXPECTED, "27/11/2026 hoặc 28/11/2026 12h30"),
    ("12h30", EXPECTED, "27/11/2026 12h30"),
])
def test_interpreted_datetime_cannot_invent_time_or_pick_ambiguous_calendar_evidence(
    booking_shop, offline_service_dependencies, query, value, proof,
):
    db, conversation, session = start(booking_shop)
    before = inventory_snapshot(db)
    result = advance_business_request(
        db, business_id=1, conversation=conversation, query=query, history=[],
        job_key=f"forged-calendar-{query}", _interpreted_action={
            "action": "collect", "action_evidence": query,
            "offering_ref": session.collected_fields["offering_ref"],
            "fields": {"starts_at": {"value": value, "evidence": proof}},
        },
    )
    assert result["state"] == "collecting"
    assert "starts_at" not in values(db, session)
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)


def test_interpreted_short_phone_is_rejected_while_valid_date_time_can_be_saved(
    booking_shop, offline_service_dependencies,
):
    db, conversation, session = start(booking_shop)
    before = inventory_snapshot(db)
    query = f"{NAME}, {INVALID_PHONE}, {DATE} 12h30"
    result = advance_business_request(
        db, business_id=1, conversation=conversation, query=query, history=[],
        job_key="forged-short-phone", _interpreted_action={
            "action": "collect", "action_evidence": query,
            "offering_ref": session.collected_fields["offering_ref"], "fields": {
                "name": {"value": NAME, "evidence": NAME},
                "phone": {"value": INVALID_PHONE, "evidence": INVALID_PHONE},
                "starts_at": {"value": EXPECTED, "evidence": f"{DATE} 12h30"},
            },
        },
    )
    collected = values(db, session)
    assert collected["name"] == NAME and collected["starts_at"] == EXPECTED
    assert "phone" not in collected
    assert "Số liên hệ" in result["invalid"]
    assert db.query(CustomerContact).filter_by(kind="phone").count() == 0
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)


def test_payment_choice_collects_but_does_not_submit_even_with_complete_fields(
    booking_shop, offline_service_dependencies,
):
    db, conversation, session = start(booking_shop)
    before = inventory_snapshot(db)
    seed_contacts(db, conversation)
    turn(db, conversation, f"{DATE} 12h30")
    before_values = deepcopy(values(db, session))
    reply = turn(db, conversation, "Chuyển khoản")
    collected = values(db, session)
    assert all(collected[key] == value for key, value in before_values.items())
    assert collected["payment_method"] == "bank_transfer"
    assert session.collected_fields["phase"] == "review"
    assert "xác nhận gửi" in reply.prompt
    assert not session.collected_fields.get("draft_order_id")
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)


@pytest.mark.parametrize("old_calendar,new_fragments,expected", [
    (DATE, ["12h30", "28/11/2026"], "2026-11-28T12:30:00+07:00"),
    ("12h30", ["28/11/2026", "13h45"], "2026-11-28T13:45:00+07:00"),
    (f"{DATE} 12h30", ["13h45", "28/11/2026"], "2026-11-28T13:45:00+07:00"),
])
def test_switching_selected_service_resets_calendar_components_from_previous_service(
    booking_shop, offline_service_dependencies, old_calendar, new_fragments, expected,
):
    db, conversation, session = start(booking_shop)
    before = inventory_snapshot(db)
    seed_contacts(db, conversation)
    turn(db, conversation, old_calendar)
    turn(db, conversation, f"tôi muốn đặt lịch hẹn {SERVICE_NAMES[0]}")
    db.refresh(session)
    assert session.collected_fields["offering_ref"] == f"service:{booking_shop[2][0].id}"
    assert "starts_at" not in values(db, session)
    # Changing services starts a fresh request; old contact approval and
    # one half of an appointment must not silently complete the new request.
    assert "name" not in values(db, session) and "phone" not in values(db, session)
    turn(db, conversation, new_fragments[0])
    assert "starts_at" not in values(db, session)
    turn(db, conversation, new_fragments[1])
    assert values(db, session)["starts_at"] == expected
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)


@pytest.mark.parametrize("old_calendar", [DATE, f"{DATE} 12h30"])
def test_cancelled_booking_calendar_is_not_reused_in_a_new_request(
    booking_shop, offline_service_dependencies, old_calendar,
):
    db, conversation, old_session = start(booking_shop)
    before = inventory_snapshot(db)
    turn(db, conversation, old_calendar)
    turn(db, conversation, "hủy lịch hẹn")
    db.refresh(old_session)
    assert old_session.status == "cancelled"
    turn(db, conversation, f"tôi muốn đặt lịch hẹn {SERVICE_NAMES[1]}")
    session = db.query(CustomerCollectionSession).filter(
        CustomerCollectionSession.status.in_(["pending", "partial"]),
    ).one()
    assert session.id != old_session.id
    turn(db, conversation, "12h30")
    assert "starts_at" not in values(db, session)
    turn(db, conversation, "28/11/2026")
    assert values(db, session)["starts_at"] == "2026-11-28T12:30:00+07:00"
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)


@pytest.mark.parametrize("proof,proposed", [
    (INVALID_PHONE, INVALID_PHONE),
    (f"{VALID_PHONE} hoặc 0901234567", VALID_PHONE),
])
def test_invalid_or_ambiguous_phone_correction_cannot_submit_previous_review(
    booking_shop, offline_service_dependencies, proof, proposed,
):
    db, conversation, session = start(booking_shop)
    before = inventory_snapshot(db)
    seed_contacts(db, conversation)
    turn(db, conversation, f"{DATE} 12h30")
    turn(db, conversation, "Chuyển khoản")
    assert session.collected_fields["phase"] == "review"
    query = f"Xác nhận gửi nhưng đổi số liên hệ {proof}"
    result = advance_business_request(
        db, business_id=1, conversation=conversation, query=query, history=[],
        job_key=f"invalid-phone-correction-{proof}", _interpreted_action={
            "action": "submit", "action_evidence": query,
            "offering_ref": session.collected_fields["offering_ref"],
            "fields": {"phone": {"value": proposed, "evidence": proof}},
        },
    )
    assert result["state"] == "collecting" and not result["order_created"]
    assert "Số liên hệ" in result["invalid"]
    assert values(db, session)["starts_at"] == EXPECTED
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)


def test_model_phone_value_absent_from_current_evidence_is_not_saved(
    booking_shop, offline_service_dependencies,
):
    db, conversation, session = start(booking_shop)
    before = inventory_snapshot(db)
    query = "Tôi sẽ gửi số điện thoại sau"
    result = advance_business_request(
        db, business_id=1, conversation=conversation, query=query, history=[],
        job_key="unsupported-current-phone", _interpreted_action={
            "action": "collect", "action_evidence": query,
            "offering_ref": session.collected_fields["offering_ref"],
            "fields": {"phone": {"value": VALID_PHONE, "evidence": query}},
        },
    )
    assert result["state"] == "collecting"
    assert "phone" not in values(db, session)
    assert db.query(CustomerContact).filter_by(kind="phone").count() == 0
    assert_only_pending(db, session, before)
    assert_no_remote_or_handoff(offline_service_dependencies)
