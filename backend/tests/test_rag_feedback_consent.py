"""Real SQL consent gates on disposable test tables, without provider calls."""
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import tenant_session as tenant_module
from app.models.channel import Channel
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.customer_collection import CustomerConsent
from app.models.message import Message
from app.models.notification import Notification
from scripts import export_rag_faq_candidates as exporter
from scripts import review_rag_feedback as reviewer

NOW = datetime(2026, 11, 4, 10, tzinfo=timezone.utc)


@pytest.fixture
def consent_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    for model in (Customer, Channel, Conversation, Message, CustomerConsent, Notification):
        model.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as db:
        for business_id, customer_id, conversation_id in ((1, 10, 100), (2, 20, 200)):
            db.add(Customer(id=customer_id, business_id=business_id, channel="web",
                            external_user_id=str(customer_id), status="active"))
            db.add(Conversation(id=conversation_id, business_id=business_id,
                                customer_id=customer_id, channel="web"))
        db.commit()
        for business_id, conversation_id, start in ((1, 100, 1000), (2, 200, 2000)):
            db.add_all([
                Message(id=start, conversation_id=conversation_id, channel="web",
                        direction="inbound", sender_type="customer", content="Câu hỏi",
                        received_at=NOW.replace(tzinfo=None)),
                Message(id=start + 1, conversation_id=conversation_id, channel="web",
                        direction="outbound", sender_type="staff", content="Trả lời",
                        sent_at=NOW.replace(tzinfo=None)),
                Notification(business_id=business_id, kind="rag_handoff_required",
                             title="handoff", metadata_={"conversation_id": conversation_id,
                                                          "question_message_id": start},
                             created_at=NOW.replace(tzinfo=None)),
            ])
        db.commit()

        @contextmanager
        def session(_schema):
            yield db

        monkeypatch.setattr(tenant_module, "tenant_session", session)
        monkeypatch.setattr(exporter, "_tenant_rows", lambda: [(1, "shop_1"), (2, "shop_2")])
        yield db
    engine.dispose()


def grant(db, business_id=1, customer_id=10, status="granted"):
    row = CustomerConsent(business_id=business_id, customer_id=customer_id,
                          purpose="faq_reuse", status=status)
    db.add(row)
    db.commit()
    return row


def decision(candidate):
    return {"candidate_id": candidate["candidate_id"],
            "content_hash": candidate["content_hash"], "business_id": 1,
            "decision": "approved", "reviewer_type": "human", "reviewer": "staff:42",
            "reviewed_at": NOW.isoformat()}


def test_export_requires_current_scoped_consent_and_not_opted_out(consent_db):
    db = consent_db
    assert exporter.collect_candidates(1) == []  # No grant.
    db.add(CustomerConsent(business_id=1, customer_id=10,
                           purpose="personalization", status="granted"))
    db.commit()
    assert exporter.collect_candidates(1) == []  # Personalization is not FAQ reuse.
    grant(db, status="revoked")
    assert exporter.collect_candidates(1) == []
    grant(db)
    rows = exporter.collect_candidates(1)
    assert len(rows) == 1 and rows[0]["business_id"] == "1"
    assert '"customer_id":10' in rows[0]["consent_provenance"]
    db.get(Customer, 10).fact_extraction_opt_out = True
    db.commit()
    assert exporter.collect_candidates(1) == []
    db.get(Customer, 10).fact_extraction_opt_out = False
    db.commit()
    grant(db, status="revoked")
    assert exporter.collect_candidates(1) == []


def test_approval_rechecks_live_consent_and_tenant(consent_db):
    db = consent_db
    grant(db)
    candidate = exporter.collect_candidates(1)[0]
    assert len(reviewer.review_candidates([candidate], [decision(candidate)], 1, NOW)) == 1
    grant(db, status="revoked")
    with pytest.raises(ValueError, match="consent"):
        reviewer.review_candidates([candidate], [decision(candidate)], 1, NOW)
    grant(db)
    db.get(Customer, 10).fact_extraction_opt_out = True
    db.commit()
    with pytest.raises(ValueError, match="consent"):
        reviewer.review_candidates([candidate], [decision(candidate)], 1, NOW)
    db.get(Customer, 10).fact_extraction_opt_out = False
    db.commit()
    with pytest.raises(ValueError, match="consent"):
        # A new grant cannot silently reuse the previously exported snapshot.
        reviewer.review_candidates([candidate], [decision(candidate)], 1, NOW)
    with pytest.raises(ValueError, match="cross-shop"):
        reviewer.review_candidates([candidate], [decision(candidate)], 2, NOW)
