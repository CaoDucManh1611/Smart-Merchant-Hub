"""Safe runtime bridge between chatbot replies and contextual-bandit experiments.

Experiments are opt-in.  A policy participates in live replies only when its
configuration declares ``runtime_binding=chatbot_auto_reply`` and contains an
``approved_arms`` mapping.  Arm values are deliberately restricted to a small
allow-list; an experiment can tune presentation, but cannot inject prompts or
execute arbitrary actions.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.experimentation import (
    BanditArmStat,
    BanditDecision,
    BanditPolicy,
    Experiment,
)
from app.models.message import Message
from app.models.conversation import Conversation
from app.models.recommendation import RecommendationCustomerProfile


RUNTIME_BINDING = "chatbot_auto_reply"
_RESPONSE_STYLES = {"balanced", "concise", "detailed"}
MIN_CHATBOT_BANDIT_OUTCOMES = 20


@dataclass(frozen=True)
class ChatbotBanditChoice:
    decision_id: int
    experiment_id: int
    arm: str
    policy_id: int
    policy_version: str
    response_style: str = "balanced"
    max_context_chunks: int | None = None

    def message_metadata(self) -> dict[str, Any]:
        return {
            "bandit": {
                "decision_id": self.decision_id,
                "experiment_id": self.experiment_id,
                "arm": self.arm,
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
            }
        }


def _context_hash(context: dict[str, Any]) -> str:
    encoded = json.dumps(
        context or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _approved_arm_configs(
    experiment: Experiment, policy: BanditPolicy
) -> dict[str, dict[str, Any]]:
    config = policy.config if isinstance(policy.config, dict) else {}
    if config.get("runtime_binding") != RUNTIME_BINDING:
        return {}
    raw_arms = config.get("approved_arms")
    if not isinstance(raw_arms, dict):
        return {}

    variants = {str(value) for value in (experiment.variants or [])}
    approved: dict[str, dict[str, Any]] = {}
    for raw_name, raw_config in raw_arms.items():
        name = str(raw_name)
        if name not in variants or not isinstance(raw_config, dict):
            continue
        # Never pass arbitrary policy text to the LLM.  Only these bounded
        # presentation controls are accepted from a human-approved policy.
        style = str(raw_config.get("response_style", "balanced"))
        if style not in _RESPONSE_STYLES:
            continue
        max_chunks = raw_config.get("max_context_chunks")
        if max_chunks is not None:
            if isinstance(max_chunks, bool) or not isinstance(max_chunks, int):
                continue
            if not 1 <= max_chunks <= 10:
                continue
        approved[name] = {
            "response_style": style,
            "max_context_chunks": max_chunks,
        }
    return approved


def select_chatbot_reply_choice(
    db: Session,
    *,
    business_id: int,
    conversation_id: int,
    channel: str,
    query_topic: str | None,
    auto_reply_key: str | None,
) -> ChatbotBanditChoice | None:
    """Select one approved arm, or return ``None`` without affecting replies."""

    candidates = (
        db.query(BanditPolicy, Experiment)
        .join(Experiment, Experiment.id == BanditPolicy.experiment_id)
        .filter(
            BanditPolicy.business_id == business_id,
            BanditPolicy.status == "active",
            Experiment.business_id == business_id,
            Experiment.status == "running",
        )
        .order_by(BanditPolicy.id.desc())
        .all()
    )
    selected: tuple[BanditPolicy, Experiment, dict[str, dict[str, Any]]] | None = None
    for policy, experiment in candidates:
        approved = _approved_arm_configs(experiment, policy)
        if approved:
            selected = policy, experiment, approved
            break
    if selected is None:
        return None

    policy, experiment, approved = selected
    policy_config = policy.config if isinstance(policy.config, dict) else {}
    source_key = auto_reply_key or f"conversation:{conversation_id}"
    idempotency_key = "chatbot-reply:" + hashlib.sha256(
        f"{business_id}:{source_key}".encode("utf-8")
    ).hexdigest()
    existing = (
        db.query(BanditDecision)
        .filter(
            BanditDecision.business_id == business_id,
            BanditDecision.experiment_id == experiment.id,
            BanditDecision.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing is not None:
        arm_config = approved.get(existing.arm)
        if arm_config is None or existing.policy_id != policy.id:
            return None
        return ChatbotBanditChoice(
            decision_id=existing.id,
            experiment_id=experiment.id,
            arm=existing.arm,
            policy_id=policy.id,
            policy_version=policy.version,
            **arm_config,
        )

    rfm_segment = (
        db.query(RecommendationCustomerProfile.segment_label)
        .join(Conversation, Conversation.customer_id == RecommendationCustomerProfile.customer_id)
        .filter(
            Conversation.id == conversation_id,
            Conversation.business_id == business_id,
            RecommendationCustomerProfile.business_id == business_id,
        )
        .scalar()
    ) or "unclassified"
    context = {
        "channel": str(channel or "unknown"),
        "query_topic": str(query_topic or "general"),
        "rfm_segment": rfm_segment,
        "runtime_binding": RUNTIME_BINDING,
    }
    context_hash = _context_hash(context)
    arms = sorted(approved)
    explore = random.random() < float(policy.epsilon)
    stats = {
        arm: db.query(BanditArmStat)
        .filter(
            BanditArmStat.business_id == business_id,
            BanditArmStat.policy_id == policy.id,
            BanditArmStat.arm == arm,
            BanditArmStat.context_hash == context_hash,
        )
        .first()
        for arm in arms
    }
    try:
        minimum_events = max(1, min(10000, int(
            policy_config.get("min_training_events", MIN_CHATBOT_BANDIT_OUTCOMES)
        )))
    except (TypeError, ValueError):
        minimum_events = MIN_CHATBOT_BANDIT_OUTCOMES
    observed_outcomes = int(db.query(func.coalesce(func.sum(BanditArmStat.pulls), 0)).filter(
        BanditArmStat.business_id == business_id,
        BanditArmStat.policy_id == policy.id,
    ).scalar() or 0)
    if observed_outcomes < minimum_events:
        arm = arms[0]
        reason = "warmup_default"
    elif explore or not any(item and item.pulls for item in stats.values()):
        arm = random.choice(arms)
        reason = "exploration"
    else:
        arm = max(
            arms,
            key=lambda item: (
                float(
                    ((stats[item].reward_sum or 0) / max(1, stats[item].pulls)) if stats[item] else 0
                ),
                item,
            ),
        )
        reason = "exploitation"

    row = BanditDecision(
        business_id=business_id,
        experiment_id=experiment.id,
        subject_key=f"conversation:{conversation_id}",
        arm=arm,
        context=context,
        policy_id=policy.id,
        policy_version=policy.version,
        context_hash=context_hash,
        selection_reason=reason,
        idempotency_key=idempotency_key,
    )
    db.add(row)
    db.flush()
    return ChatbotBanditChoice(
        decision_id=row.id,
        experiment_id=experiment.id,
        arm=arm,
        policy_id=policy.id,
        policy_version=policy.version,
        **approved[arm],
    )


def response_style_instruction(style: str) -> str | None:
    """Return a fixed, reviewed instruction for an approved style arm."""

    if style == "concise":
        return "Trả lời ngắn gọn, đi thẳng vào câu hỏi và không lặp lại thông tin."
    if style == "detailed":
        return "Trả lời rõ ràng, có đủ bước cần thiết nhưng không suy đoán ngoài dữ liệu."
    return None


def record_message_feedback_reward(
    db: Session,
    *,
    business_id: int,
    message: Message,
    rating: int,
) -> BanditDecision | None:
    """Convert binary reply feedback into one tenant-scoped bandit reward.

    The canonical key is tied to the saved outbound message, so UI retries or
    different client idempotency keys cannot increment arm statistics twice.
    """

    metadata = message.metadata_ if isinstance(message.metadata_, dict) else {}
    bandit = metadata.get("bandit")
    if not isinstance(bandit, dict):
        return None
    try:
        decision_id = int(bandit["decision_id"])
    except (KeyError, TypeError, ValueError):
        return None
    decision = (
        db.query(BanditDecision)
        .filter(
            BanditDecision.id == decision_id,
            BanditDecision.business_id == business_id,
        )
        .first()
    )
    if decision is None:
        return None

    reward_key = f"chatbot-feedback:{business_id}:{message.id}"
    if decision.reward is not None:
        # First explicit rating wins. Repeated delivery is idempotent and a
        # later conflicting click does not silently corrupt accumulated stats.
        return decision

    reward = Decimal("1") if int(rating) > 0 else Decimal("-1")
    decision.reward = reward
    decision.reward_idempotency_key = reward_key
    if decision.policy_id and decision.context_hash:
        stat = (
            db.query(BanditArmStat)
            .filter(
                BanditArmStat.business_id == business_id,
                BanditArmStat.policy_id == decision.policy_id,
                BanditArmStat.arm == decision.arm,
                BanditArmStat.context_hash == decision.context_hash,
            )
            .first()
        )
        if stat is None:
            stat = BanditArmStat(
                business_id=business_id,
                policy_id=decision.policy_id,
                arm=decision.arm,
                context_hash=decision.context_hash,
                pulls=0,
                reward_sum=Decimal("0"),
            )
            db.add(stat)
        stat.pulls = int(stat.pulls or 0) + 1
        stat.reward_sum = Decimal(stat.reward_sum or 0) + reward
    return decision
