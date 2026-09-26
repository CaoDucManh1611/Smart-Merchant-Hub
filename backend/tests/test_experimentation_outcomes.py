from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register tenant models
from app.api.experimentation import _confirmed_conversation_outcome_summary, _conversation_outcome_summary
from app.database.bases import TenantBase
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.message import Message


def test_conversation_outcomes_are_tenant_scoped_and_state_based():
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            customer = Customer(business_id=7, channel="web", external_user_id="customer-1", name="Customer")
            db.add(customer)
            db.flush()
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            conversations = [
                Conversation(business_id=7, customer_id=customer.id, channel="web", status="closed", resolution_outcome="resolved"),
                Conversation(business_id=7, customer_id=customer.id, channel="web", status="open", bot_mode="human", resolution_outcome="needs_human"),
                Conversation(business_id=7, customer_id=customer.id, channel="web", status="open"),
                Conversation(business_id=7, customer_id=customer.id, channel="web", status="open", resolution_outcome="customer_unanswered"),
                Conversation(business_id=8, customer_id=customer.id, channel="web", status="closed", resolution_outcome="resolved"),
            ]
            db.add_all(conversations)
            db.flush()
            db.add_all([
                Message(conversation_id=conversations[2].id, channel="web", direction="outbound", received_at=now - timedelta(hours=25)),
                Message(conversation_id=conversations[3].id, channel="web", direction="inbound", received_at=now),
            ])
            db.commit()
            result = _conversation_outcome_summary(
                db, business_id=7, conversation_ids={conversation.id for conversation in conversations}
            )
            confirmed = _confirmed_conversation_outcome_summary(
                db, business_id=7, conversation_ids={conversation.id for conversation in conversations[:4]}
            )
        assert result == {"resolved": 1, "needs_human": 1, "customer_unanswered": 1, "in_progress": 1}
        assert confirmed == {"resolved": 1, "needs_human": 1, "customer_unanswered": 1, "unclassified": 1}
    finally:
        engine.dispose()
