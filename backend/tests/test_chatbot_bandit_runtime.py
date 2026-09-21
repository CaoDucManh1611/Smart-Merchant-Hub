from decimal import Decimal
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.experimentation import (
    BanditArmStat,
    BanditDecision,
    BanditPolicy,
    Experiment,
)
from app.models.message import Message
from app.services.chatbot_bandit_service import (
    ChatbotBanditChoice,
    select_chatbot_reply_choice,
)
from app.services.auto_reply_service import process_rag_auto_reply


def _runtime_policy(db: Session, business_id: int):
    experiment = Experiment(
        business_id=business_id,
        name="Chatbot response style",
        variants=["control", "concise"],
        status="running",
    )
    db.add(experiment)
    db.flush()
    policy = BanditPolicy(
        business_id=business_id,
        experiment_id=experiment.id,
        version="approved-v1",
        epsilon=Decimal("0"),
        status="active",
        config={
            "runtime_binding": "chatbot_auto_reply",
            "approved_arms": {
                "control": {"response_style": "balanced"},
                "concise": {
                    "response_style": "concise",
                    "max_context_chunks": 3,
                },
            },
        },
    )
    db.add(policy)
    db.flush()
    return experiment, policy


def test_runtime_selection_is_opt_in_approved_and_idempotent():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Business.metadata.create_all(engine)
    with Session(engine) as db:
        business = Business(name="Bandit Shop", slug="bandit-shop")
        db.add(business)
        db.flush()
        experiment, policy = _runtime_policy(db, business.id)

        first = select_chatbot_reply_choice(
            db,
            business_id=business.id,
            conversation_id=42,
            channel="telegram",
            query_topic="returns",
            auto_reply_key="inbound:1:42:100:rag",
        )
        second = select_chatbot_reply_choice(
            db,
            business_id=business.id,
            conversation_id=42,
            channel="telegram",
            query_topic="returns",
            auto_reply_key="inbound:1:42:100:rag",
        )

        assert first is not None
        assert second is not None
        assert first.decision_id == second.decision_id
        assert first.arm in {"control", "concise"}
        assert first.policy_id == policy.id
        assert db.query(BanditDecision).filter_by(experiment_id=experiment.id).count() == 1


def test_policy_without_runtime_binding_does_not_touch_live_chatbot():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Business.metadata.create_all(engine)
    with Session(engine) as db:
        business = Business(name="Safe Shop", slug="safe-shop")
        db.add(business)
        db.flush()
        experiment = Experiment(
            business_id=business.id,
            name="Offline only",
            variants=["a", "b"],
            status="running",
        )
        db.add(experiment)
        db.flush()
        db.add(
            BanditPolicy(
                business_id=business.id,
                experiment_id=experiment.id,
                version="offline-v1",
                epsilon=Decimal("0.1"),
                config={"prompt": "This must never reach the live bot"},
                status="active",
            )
        )
        db.flush()

        choice = select_chatbot_reply_choice(
            db,
            business_id=business.id,
            conversation_id=1,
            channel="telegram",
            query_topic="general",
            auto_reply_key="inbound:1:1:1:rag",
        )

        assert choice is None
        assert db.query(BanditDecision).count() == 0


def test_feedback_becomes_one_traced_reward_and_is_tenant_safe():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Business.metadata.create_all(engine)
    with Session(engine) as db:
        business = Business(name="Reward Shop", slug="reward-shop")
        other = Business(name="Other Shop", slug="other-shop")
        db.add_all([business, other])
        db.flush()
        customer = Customer(
            business_id=business.id,
            channel="telegram",
            external_user_id="reward-customer",
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
        _, policy = _runtime_policy(db, business.id)
        choice = select_chatbot_reply_choice(
            db,
            business_id=business.id,
            conversation_id=conversation.id,
            channel="telegram",
            query_topic="general",
            auto_reply_key="inbound:1:1:99:rag",
        )
        assert choice is not None
        message = Message(
            conversation_id=conversation.id,
            channel="telegram",
            sender_type="bot",
            direction="outbound",
            content="Câu trả lời thử nghiệm",
            metadata_=choice.message_metadata(),
        )
        db.add(message)
        db.commit()
        business_id = business.id
        other_id = other.id
        message_id = message.id
        decision_id = choice.decision_id
        policy_id = policy.id

    def override_get_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        first = client.post(
            f"/api/chatbot/messages/{message_id}/feedback",
            headers={"X-Business-Id": str(business_id)},
            json={"rating": 1, "idempotency_key": "ui-click-1"},
        )
        repeated = client.post(
            f"/api/chatbot/messages/{message_id}/feedback",
            headers={"X-Business-Id": str(business_id)},
            json={"rating": 1, "idempotency_key": "ui-click-1"},
        )
        hidden = client.post(
            f"/api/chatbot/messages/{message_id}/feedback",
            headers={"X-Business-Id": str(other_id)},
            json={"rating": -1, "idempotency_key": "cross-tenant"},
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert hidden.status_code == 404
    with Session(engine) as db:
        decision = db.get(BanditDecision, decision_id)
        assert decision.reward == Decimal("1.0000")
        assert decision.reward_idempotency_key == f"chatbot-feedback:{business_id}:{message_id}"
        stat = db.query(BanditArmStat).filter_by(policy_id=policy_id, arm=decision.arm).one()
        assert stat.pulls == 1
        assert stat.reward_sum == Decimal("1.000000")


def test_rag_reply_applies_only_bounded_arm_and_saves_decision_trace():
    db = Mock()
    conversation = Mock(id=7, customer_id=8, bot_mode="auto")
    db.query().filter().first.side_effect = [None, conversation]
    chunks = [
        Mock(document_id=index, similarity=0.9, content=f"context {index}")
        for index in range(1, 6)
    ]
    choice = ChatbotBanditChoice(
        decision_id=21,
        experiment_id=4,
        arm="concise",
        policy_id=9,
        policy_version="approved-v1",
        response_style="concise",
        max_context_chunks=3,
    )

    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service.customer_order_reply", return_value=None), \
        patch("app.services.product_pricing.combo_price_comparison_reply", return_value=None), \
        patch("app.services.auto_reply_service._deterministic_customer_reply", return_value=None), \
        patch("app.services.auto_reply_service.is_browsing_request", return_value=False), \
        patch("app.services.auto_reply_service.retrieve", return_value=chunks), \
        patch("app.services.auto_reply_service.select_chatbot_reply_choice", return_value=choice), \
        patch("app.services.auto_reply_service.build_agent_memory", return_value={"history": []}), \
        patch("app.services.auto_reply_service.build_prompt", return_value=[{"role": "user", "content": "q"}]) as build_prompt, \
        patch("app.services.auto_reply_service.record_quota_usage"), \
        patch("app.services.auto_reply_service.estimate_ai_cost", return_value=Decimal("0")), \
        patch("app.services.auto_reply_service.call_llm", return_value="Câu trả lời"), \
        patch("app.services.auto_reply_service._get_conversation_recipient", return_value=("telegram", "customer-1")), \
        patch("app.services.auto_reply_service._send_channel_reply", return_value={"message_id": "out-1"}), \
        patch("app.services.auto_reply_service._save_auto_reply_outbound") as save:
        result = process_rag_auto_reply(
            db=db,
            conversation_id=7,
            channel="telegram",
            query_text="Chính sách thanh toán thế nào?",
            business_id=1,
        )

    assert result is True
    assert len(build_prompt.call_args.kwargs["chunks"]) == 3
    assert "Trả lời ngắn gọn" in build_prompt.call_args.kwargs["system_prompt"]
    assert save.call_args.kwargs["extra_metadata"]["bandit"] == {
        "decision_id": 21,
        "experiment_id": 4,
        "arm": "concise",
        "policy_id": 9,
        "policy_version": "approved-v1",
    }
