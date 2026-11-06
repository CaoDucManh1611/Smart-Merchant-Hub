"""Memory contract against a disposable DB; conftest chooses the real dialect."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.channel import Channel
from app.models.customer_collection import CustomerConsent
from app.models.crm_job import CrmJob
from app.models.message import Message
from app.models.sales import Product
from app.services.conversation_memory import (
    MEMORY_KEY, build_reply_memory, load_reply_memory, purge_reply_memory_for_customer,
    resolve_memory_products,
)

NOW = datetime(2026, 11, 4, 10, tzinfo=timezone.utc)
NAME = "Lốp Michelin City 70/90-17"
OTHER = "Lốp IRC Urban 70/90-17"


@pytest.fixture
def fake_db():
    engine = create_engine("sqlite:///:memory:")
    # The default harness remaps this URL to isolated PostgreSQL schemas.
    # Create FK dependencies too; do not depend on SQLite's relaxed FK checks.
    for model in (Customer, Channel, Conversation, Product, Message, CustomerConsent, CrmJob):
        model.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add_all([Customer(id=i, business_id=b, channel="web", external_user_id=str(i))
                    for i, b in ((11, 1), (22, 2), (33, 1), (99, 1))])
        db.commit()
        db.add_all([
            Conversation(id=10, business_id=1, customer_id=11, channel="web"),
            Conversation(id=20, business_id=2, customer_id=22, channel="web"),
            Conversation(id=30, business_id=None, customer_id=33, channel="web"),
            Product(id=1, business_id=1, sku="A", name=NAME, price=250000,
                    stock_quantity=5, status="active", metadata_={"aliases": ["70/90-17"]}),
            Product(id=2, business_id=1, sku="B", name=OTHER, price=200000,
                    stock_quantity=7, status="active"),
            Product(id=3, business_id=2, sku="A", name=NAME, price=100000,
                    stock_quantity=90, status="active"),
            Product(id=4, business_id=1, sku="C", name="Lốp Michelin City 80/90-17",
                    price=300000, stock_quantity=2, status="active"),
        ])
        db.commit()
        yield db
    engine.dispose()


def test_fixture_reports_actual_engine(fake_db):
    dialect = fake_db.bind.dialect.name
    print("memory fixture actual dialect: " + dialect)
    assert dialect in {"sqlite", "postgresql"}


def save_reply(db, answer=NAME, **kwargs):
    state = build_reply_memory(db, 1, 10, kwargs.pop("query", "So sánh"), answer, now=NOW, **kwargs)
    message = Message(id=100, conversation_id=10, sender_type="bot", direction="outbound",
                      channel="web", status="sent", sent_at=NOW.replace(tzinfo=None),
                      content=answer, metadata_={MEMORY_KEY: state})
    db.add(message)
    db.commit()
    return message, state


def test_exact_full_names_do_not_widen_to_shared_tire_dimension(fake_db):
    message, state = save_reply(fake_db)
    assert state["scope"] == {"business_id": 1, "customer_id": 11, "conversation_id": 10}
    assert state["active_product_ids"] == [1]
    assert load_reply_memory(fake_db, 1, 10, NOW)["active_product_ids"] == [1]
    assert [p.id for p in resolve_memory_products(fake_db, 1, 10, "Cái đó còn hàng không?", NOW)] == [1]
    assert "price" not in state and "stock_quantity" not in state


@pytest.mark.parametrize("answer", ["70/90-17 còn hàng", "Lốp Michelin City 70/90", "Lop Michelin City 70/90-17", "A"])
def test_dimensions_short_names_fuzzy_and_sku_alone_are_not_display_evidence(fake_db, answer):
    assert build_reply_memory(fake_db, 1, 10, "", answer, product_ids=[1, 2], now=NOW)["active_product_ids"] == []


def test_product_id_hints_cannot_bypass_full_name_or_tenant(fake_db):
    assert build_reply_memory(fake_db, 1, 10, "", NAME, [2, 3], NOW)["active_product_ids"] == []
    assert build_reply_memory(fake_db, 1, 10, "", NAME, [], NOW)["active_product_ids"] == []
    assert build_reply_memory(fake_db, 1, 10, "", NAME, [1, 3], NOW)["active_product_ids"] == [1]


def test_ambiguous_alias_is_checked_against_whole_shop_before_id_hints(fake_db):
    fake_db.get(Product, 2).metadata_ = {"aliases": [NAME]}
    fake_db.commit()
    assert build_reply_memory(fake_db, 1, 10, "", NAME, [1], NOW)["active_product_ids"] == []


def test_longer_full_label_does_not_also_capture_shorter_label(fake_db):
    fake_db.get(Product, 2).name = NAME + " Plus"
    fake_db.commit()
    assert build_reply_memory(fake_db, 1, 10, "", NAME + " Plus", now=NOW)["active_product_ids"] == [2]


def test_localized_curated_full_display_name(fake_db):
    fake_db.get(Product, 1).metadata_ = {"display_names": {"en": "Michelin City Tire 70/90-17"}}
    fake_db.commit()
    assert build_reply_memory(fake_db, 1, 10, "", "Michelin City Tire 70/90-17", now=NOW)["active_product_ids"] == [1]


def test_dimension_only_alias_with_unit_is_still_not_identity(fake_db):
    fake_db.get(Product, 1).metadata_ = {"aliases": ["70/90-17 mm", "size 70/90 R17"]}
    fake_db.commit()
    for answer in ("70/90-17 mm", "size 70/90 R17"):
        assert build_reply_memory(fake_db, 1, 10, "", answer, now=NOW)["active_product_ids"] == []


def test_explicit_budget_qty_pending_and_intent_without_price_stock_snapshots(fake_db):
    state = build_reply_memory(fake_db, 1, 10, "Ngân sách 1,5 triệu, mua 2 cái, so sánh giúp mình",
                               NAME + ": 250.000đ, còn 5. Bạn cần kích thước nào?", now=NOW)
    assert state["constraints"] == {"budget": {"amount": 1500000, "currency": "VND", "operator": "lte"}, "qty": 2}
    assert state["pending_slot"] == "variant"
    assert state["last_intent"] == "compare"
    assert build_reply_memory(fake_db, 1, 10, "Giá 250000 đồng, còn 5", NAME, now=NOW)["constraints"] == {}


def test_ttl_in_metadata_only_and_exact_expiry_boundary(fake_db):
    _, state = save_reply(fake_db)
    assert state["expires_at"] == (NOW + timedelta(minutes=30)).isoformat()
    assert load_reply_memory(fake_db, 1, 10, NOW + timedelta(minutes=29, seconds=59))["active_product_ids"] == [1]
    assert load_reply_memory(fake_db, 1, 10, NOW + timedelta(minutes=30))["active_product_ids"] == []
    assert load_reply_memory(fake_db, 1, 10, NOW - timedelta(seconds=1))["active_product_ids"] == []


@pytest.mark.parametrize("query,amount", [("Ngân sách 500.000 đồng", 500000),
                                         ("Tối đa 1.500.000 VND", 1500000), ("Dưới 500k", 500000)])
def test_explicit_budget_keeps_vietnamese_grouped_currency_amount(fake_db, query, amount):
    assert build_reply_memory(fake_db, 1, 10, query, NAME, now=NOW)["constraints"]["budget"]["amount"] == amount


def test_external_customer_reassignment_and_sent_status_refresh_identity_map(fake_db):
    message, _ = save_reply(fake_db)
    with fake_db.bind.begin() as connection:
        connection.execute(update(Message).where(Message.id == message.id).values(status="failed"))
    assert load_reply_memory(fake_db, 1, 10, NOW)["active_product_ids"] == []
    with fake_db.bind.begin() as connection:
        connection.execute(update(Message).where(Message.id == message.id).values(status="sent"))
        connection.execute(update(Conversation).where(Conversation.id == 10).values(customer_id=99))
    assert load_reply_memory(fake_db, 1, 10, NOW)["active_product_ids"] == []


@pytest.mark.parametrize("status", ["failed", "sending", "received"])
def test_unsent_outbound_cannot_supply_state(fake_db, status):
    message, _ = save_reply(fake_db)
    message.status = status
    fake_db.commit()
    assert load_reply_memory(fake_db, 1, 10, NOW)["active_product_ids"] == []


@pytest.mark.parametrize("metadata,status", [({}, "sent"), ({}, "failed"), ({MEMORY_KEY: {}}, "sent")])
def test_newer_reply_is_barrier_even_when_previous_metadata_ttl_valid(fake_db, metadata, status):
    save_reply(fake_db)
    fake_db.add(Message(id=101, conversation_id=10, sender_type="staff", direction="outbound",
                        channel="web", status=status, sent_at=NOW.replace(tzinfo=None),
                        content="Chuyển chủ đề", metadata_=metadata))
    fake_db.commit()
    assert load_reply_memory(fake_db, 1, 10, NOW)["active_product_ids"] == []


def test_only_one_customer_turn_after_reply_is_allowed(fake_db):
    save_reply(fake_db)
    for message_id in (101, 102):
        fake_db.add(Message(id=message_id, conversation_id=10, sender_type="customer", direction="inbound",
                            channel="web", status="received", content="Còn hàng không?"))
        fake_db.commit()
        assert load_reply_memory(fake_db, 1, 10, NOW)["active_product_ids"] == ([1] if message_id == 101 else [])


def test_scope_validation_and_missing_tenant_never_default_to_caller(fake_db):
    _, state = save_reply(fake_db)
    assert load_reply_memory(fake_db, 2, 10, NOW)["active_product_ids"] == []
    assert load_reply_memory(fake_db, 1, 20, NOW)["active_product_ids"] == []
    assert build_reply_memory(fake_db, 1, 30, "", NAME, now=NOW) is None
    fake_db.add(Message(id=200, conversation_id=20, sender_type="bot", direction="outbound",
                        channel="web", status="sent", sent_at=NOW.replace(tzinfo=None),
                        content=NAME, metadata_={MEMORY_KEY: state}))
    fake_db.commit()
    assert load_reply_memory(fake_db, 2, 20, NOW)["active_product_ids"] == []
    fake_db.get(Conversation, 10).customer_id = 99
    fake_db.commit()
    assert load_reply_memory(fake_db, 1, 10, NOW)["active_product_ids"] == []


def test_revoked_personalization_consent_blocks_memory_read_write_and_scoped_purge(fake_db):
    message, state = save_reply(fake_db)
    message.metadata_ = {MEMORY_KEY: state, "route": "direct_rag"}
    unrelated = Message(
        id=200, conversation_id=20, sender_type="bot", direction="outbound",
        channel="web", status="sent", sent_at=NOW.replace(tzinfo=None),
        content=NAME, metadata_={MEMORY_KEY: state, "route": "other_shop"},
    )
    fake_db.add(unrelated)
    fake_db.add(CustomerConsent(
        business_id=1, customer_id=11, purpose="personalization", status="revoked",
        revoked_at=NOW.replace(tzinfo=None),
    ))
    fake_db.commit()

    assert load_reply_memory(fake_db, 1, 10, NOW)["active_product_ids"] == []
    assert build_reply_memory(fake_db, 1, 10, "Cái đó còn hàng không?", NAME, now=NOW) is None

    assert purge_reply_memory_for_customer(fake_db, 1, 11) == 1
    assert message.metadata_ == {"route": "direct_rag"}
    assert MEMORY_KEY in unrelated.metadata_


def test_fact_collection_opt_out_blocks_memory_even_without_consent_row(fake_db):
    fake_db.get(Customer, 11).fact_extraction_opt_out = True
    fake_db.commit()
    assert build_reply_memory(fake_db, 1, 10, "mua 2 cái", NAME, now=NOW) is None
    assert load_reply_memory(fake_db, 1, 10, NOW)["active_product_ids"] == []


def test_personalization_cleanup_calls_reply_memory_purge(monkeypatch):
    from app.services import conversation_memory, privacy_service

    class EmptyRows:
        def all(self):
            return []

    class EmptyDB:
        def scalars(self, statement):
            return EmptyRows()

    calls = []
    monkeypatch.setattr(
        conversation_memory, "purge_reply_memory_for_customer",
        lambda db, business_id, customer_id: calls.append((db, business_id, customer_id)) or 0,
    )
    monkeypatch.setattr(privacy_service, "_scrub_personalized_bandit_decisions", lambda *args: None)
    monkeypatch.setattr(privacy_service, "_invalidate_consent_derived_models", lambda *args: None)
    db = EmptyDB()

    privacy_service.stop_customer_personalization(db, 1, 11)

    assert calls == [(db, 1, 11)]


def test_fact_opt_out_scrubs_reply_memory_even_when_other_history_is_retained(monkeypatch):
    from app.api import customers as customers_api
    from app.schemas.customer import CustomerFactCollectionRequest
    from app.services import conversation_memory

    customer = SimpleNamespace(fact_extraction_opt_out=False)
    calls = []
    lock_requests = []
    db = SimpleNamespace(commit=lambda: None)
    monkeypatch.setattr(
        customers_api, "_get_customer",
        lambda *args, **kwargs: lock_requests.append(kwargs.get("lock", False)) or customer,
    )
    monkeypatch.setattr(customers_api, "record_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        conversation_memory, "purge_reply_memory_for_customer",
        lambda *args: calls.append(args) or 1,
    )

    result = customers_api.set_customer_fact_collection(
        11,
        CustomerFactCollectionRequest(opt_out=True, delete_existing_extracted=False),
        db,
        SimpleNamespace(business_id=1),
        None,
    )

    assert result.opt_out is True
    assert result.deleted_extracted_facts == 0
    assert lock_requests == [True]
    assert calls == [(db, 1, 11)]


def test_locked_customer_lookup_uses_scoped_row_lock():
    from app.api import customers as customers_api

    customer = SimpleNamespace(id=11, business_id=1)

    class Query:
        locked = False
        populated = False

        def filter(self, *criteria):
            self.criteria = criteria
            return self

        def populate_existing(self):
            self.populated = True
            return self

        def with_for_update(self):
            self.locked = True
            return self

        def first(self):
            return customer

    query = Query()

    class DB:
        def query(self, model):
            assert model is Customer
            return query

    assert customers_api._get_customer(DB(), 11, SimpleNamespace(business_id=1), lock=True) is customer
    assert query.locked and query.populated
    assert len(query.criteria) == 2


@pytest.mark.parametrize("change", [
    {"schema_version": 99}, {"schema_version": True}, {"expires_at": "invalid"},
    {"pending_slot": []}, {"last_intent": {}}, {"active_product_ids": [True]},
    {"created_at": (NOW + timedelta(minutes=1)).isoformat()},
    {"expires_at": (NOW + timedelta(hours=1)).isoformat()},
])
def test_malformed_or_forged_metadata_fails_closed(fake_db, change):
    message, state = save_reply(fake_db)
    message.metadata_ = {MEMORY_KEY: {**state, **change}}
    # SQLAlchemy compares JSON by Python equality: True == 1. Force the
    # forged payload into the database before testing the read-side guard.
    flag_modified(message, "metadata_")
    fake_db.commit()
    assert load_reply_memory(fake_db, 1, 10, NOW)["active_product_ids"] == []


def test_ids_reproved_against_answer_and_inactive_current_catalog(fake_db):
    message, state = save_reply(fake_db)
    changed = deepcopy(state)
    changed["active_product_ids"] = [1, 2, 3]
    changed["price"] = 123
    changed["constraints"]["stock"] = 999
    message.metadata_ = {MEMORY_KEY: changed}
    fake_db.commit()
    loaded = load_reply_memory(fake_db, 1, 10, NOW)
    assert loaded["active_product_ids"] == [1]
    assert "price" not in loaded and "stock" not in loaded["constraints"]
    fake_db.get(Product, 1).status = "inactive"
    fake_db.commit()
    assert load_reply_memory(fake_db, 1, 10, NOW)["active_product_ids"] == []


def test_real_vietnamese_cheaper_stock_followup_and_fresh_identity_map(fake_db):
    save_reply(fake_db, NAME + " và " + OTHER)
    stale = fake_db.get(Product, 1)
    assert stale.price == 250000 and stale.stock_quantity == 5
    with fake_db.bind.begin() as connection:
        connection.execute(update(Product).where(Product.id == 1).values(price=175000, stock_quantity=42))
    candidates = resolve_memory_products(fake_db, 1, 10, "Loại rẻ hơn còn bao nhiêu cái?", NOW)
    assert [p.id for p in candidates] == [1, 2]  # Main selects cheaper from current facts.
    assert candidates[0] is stale and stale.price == 175000 and stale.stock_quantity == 42


@pytest.mark.parametrize("query", ["SerumZZ9 còn hàng không?", "Cái đó và SerumZZ9 giá bao nhiêu?",
                                  "Chiếc váy này giá bao nhiêu?", "70/90-17 còn hàng không?",
                                  "Đổi chủ đề, cái đó còn hàng không?", "reset", "Xin chào"])
def test_new_topic_unknown_identity_and_reset_do_not_reuse(fake_db, query):
    save_reply(fake_db)
    assert resolve_memory_products(fake_db, 1, 10, query, NOW) == []


def test_explicit_reset_builds_empty_state_even_if_answer_names_product(fake_db):
    state = build_reply_memory(fake_db, 1, 10, "Bắt đầu lại", NAME, [1], NOW)
    assert state["active_product_ids"] == [] and state["constraints"] == {}
    assert state["last_intent"] == "reset"


def test_direct_rag_saved_outbound_persists_memory_for_followup(fake_db, monkeypatch):
    from app.services import auto_reply_service

    for side_effect in ("_record_auto_reply_sent", "_record_sent_recommendation_exposure",
                        "_schedule_saved_message_event"):
        monkeypatch.setattr(auto_reply_service, side_effect, lambda *args, **kwargs: None)
    fake_db.add_all([
        Message(id=300, conversation_id=10, sender_type="customer", direction="inbound",
                channel="web", status="received", content="Lốp Michelin City còn hàng không?"),
        Message(id=301, conversation_id=10, sender_type="bot", direction="outbound",
                channel="web", status="sending", auto_reply_key="direct-rag-301", content=""),
    ])
    fake_db.commit()
    auto_reply_service._save_auto_reply_outbound(
        fake_db, 10, "web", "recipient", "provider-301", NAME,
        {"message_id": "provider-301"}, auto_reply_key="direct-rag-301",
        extra_metadata={"route": "direct_rag"},
    )
    saved = fake_db.get(Message, 301)
    assert saved.status == "sent" and saved.metadata_["route"] == "direct_rag"
    assert saved.metadata_[MEMORY_KEY]["active_product_ids"] == [1]
    assert [p.id for p in resolve_memory_products(fake_db, 1, 10, "Cái đó còn hàng không?")] == [1]
