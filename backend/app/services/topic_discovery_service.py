"""Tenant-safe topic discovery for inbound customer messages.

The service is deliberately read-only.  It turns messages into reviewable
topic suggestions, but never edits documents, prompts, or bot behaviour.
Existing message embeddings are used when they are present and consistent;
otherwise a local deterministic hash embedding keeps the endpoint fast and
independent from remote embedding quotas.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.message import Message


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP_WORDS = {
    "a", "anh", "ban", "bi", "cai", "cho", "co", "cua", "em", "gi", "ha",
    "hay", "khach", "khong", "la", "lam", "minh", "mot", "nay", "nhe", "oi",
    "shop", "thi", "toi", "va", "voi", "duoc",
}
_KNOWN_TOPICS = (
    ("pricing", "Giá và sản phẩm", {"gia", "san", "pham", "mau", "size", "kich", "thuoc", "tinh"}),
    ("order_delivery", "Đơn hàng và giao hàng", {"don", "dat", "mua", "giao", "ship", "van", "chuyen", "cod"}),
    ("payment", "Thanh toán", {"thanh", "toan", "chuyen", "khoan", "the", "cod", "hoa", "don"}),
    ("returns_warranty", "Đổi trả và bảo hành", {"doi", "tra", "hoan", "bao", "hanh", "loi", "hong"}),
    ("support_complaint", "Hỗ trợ và khiếu nại", {"khieu", "nai", "phan", "nan", "ho", "tro", "loi"}),
)


def _normalise(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFD", str(value or "").lower())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _tokens(value: str | None) -> list[str]:
    return [
        token for token in _TOKEN_PATTERN.findall(_normalise(value))
        if len(token) > 1 and token not in _STOP_WORDS
    ]


def _hash_embedding(value: str | None, dimensions: int = 256) -> list[float]:
    """Create a stable local embedding without model training or network I/O."""

    vector = [0.0] * dimensions
    tokens = _tokens(value)
    features = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]
    for feature in features:
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        vector[int.from_bytes(digest[:4], "big") % dimensions] += 1.0
    return _normalise_vector(vector)


def _normalise_vector(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(item) ** 2 for item in vector))
    if norm <= 0:
        return [0.0 for _ in vector]
    return [float(item) / norm for item in vector]


def _stored_embedding(message: Message) -> list[float] | None:
    metadata = message.metadata_ if isinstance(message.metadata_, dict) else {}
    candidate = metadata.get("topic_embedding") or metadata.get("embedding")
    if not isinstance(candidate, list) or not 2 <= len(candidate) <= 4096:
        return None
    if not all(isinstance(item, (int, float)) and math.isfinite(float(item)) for item in candidate):
        return None
    vector = _normalise_vector(candidate)
    return vector if any(vector) else None


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _centroid(vectors: Sequence[Sequence[float]]) -> list[float]:
    dimension = len(vectors[0])
    return _normalise_vector([
        sum(vector[index] for vector in vectors) / len(vectors)
        for index in range(dimension)
    ])


def _cluster_vectors(vectors: Sequence[Sequence[float]], threshold: float) -> list[list[int]]:
    """Greedy deterministic clustering suitable for a bounded admin preview."""

    clusters: list[list[int]] = []
    centroids: list[list[float]] = []
    for index, vector in enumerate(vectors):
        if not clusters:
            clusters.append([index])
            centroids.append(list(vector))
            continue
        scores = [_cosine(vector, center) for center in centroids]
        best = max(range(len(scores)), key=lambda item: scores[item])
        if scores[best] >= threshold:
            clusters[best].append(index)
            centroids[best] = _centroid([vectors[item] for item in clusters[best]])
        else:
            clusters.append([index])
            centroids.append(list(vector))
    return clusters


def _topic_label(messages: Iterable[Message], top_terms: list[str]) -> tuple[str, str]:
    words = Counter(_tokens(" ".join(str(message.content or "") for message in messages)))
    best_key, best_label, best_score = "", "", 0
    for key, label, keywords in _KNOWN_TOPICS:
        score = sum(words[word] for word in keywords)
        if score > best_score:
            best_key, best_label, best_score = key, label, score
    if best_score:
        return best_key, best_label
    label_terms = top_terms[:3] or ["khác"]
    return "discovered", "Chủ đề: " + ", ".join(label_terms)


def discover_topic_suggestions(
    messages: Sequence[Message],
    *,
    min_cluster_size: int = 2,
    max_topics: int = 12,
    similarity_threshold: float = 0.24,
) -> dict:
    """Discover review candidates from an already tenant-scoped message set.

    This is analysis, not an in-request model training job.  The function uses
    no remote provider and has no database side effects.
    """

    usable = [message for message in messages if _tokens(message.content)]
    usable.sort(key=lambda message: (int(message.id or 0), str(message.content or "")))
    stored = [_stored_embedding(message) for message in usable]
    stored_dimensions = {len(vector) for vector in stored if vector is not None}
    use_stored = bool(usable) and len(stored_dimensions) == 1 and all(vector is not None for vector in stored)
    vectors = [list(vector) for vector in stored] if use_stored else [_hash_embedding(message.content) for message in usable]
    source = "stored_embeddings" if use_stored else "deterministic_local_embedding"

    clusters = _cluster_vectors(vectors, similarity_threshold) if vectors else []
    suggestions = []
    for indexes in clusters:
        if len(indexes) < min_cluster_size:
            continue
        cluster_messages = [usable[index] for index in indexes]
        terms = Counter(
            token
            for message in cluster_messages
            for token in _tokens(message.content)
        )
        top_terms = [word for word, _count in terms.most_common(8)]
        topic_key, label = _topic_label(cluster_messages, top_terms)
        center = _centroid([vectors[index] for index in indexes])
        confidence = sum(_cosine(vectors[index], center) for index in indexes) / len(indexes)
        stable_basis = "|".join(sorted(top_terms[:5])) or label
        suffix = hashlib.sha256(stable_basis.encode("utf-8")).hexdigest()[:10]
        suggestions.append({
            "suggestion_id": f"{topic_key}:{suffix}",
            "label": label,
            "message_count": len(cluster_messages),
            "conversation_count": len({int(message.conversation_id) for message in cluster_messages}),
            "examples": [str(message.content).strip()[:160] for message in cluster_messages[:3]],
            "top_terms": top_terms,
            "confidence": round(max(0.0, min(confidence, 1.0)), 4),
            "review_status": "pending_review",
            "source": source,
        })

    suggestions.sort(key=lambda item: (-item["message_count"], item["suggestion_id"]))
    return {
        "messages_analyzed": len(usable),
        "conversations_sampled": len({int(message.conversation_id) for message in usable}),
        "suggestions": suggestions[:max_topics],
        "method": (
            "Dùng vector đã lưu; chỉ tạo đề xuất chờ quản trị viên duyệt"
            if use_stored
            else "Dùng vector cục bộ ổn định; chỉ tạo đề xuất chờ quản trị viên duyệt"
        ),
        "knowledge_base_updated": False,
    }


def tenant_topic_suggestions(
    db: Session,
    business_id: int,
    *,
    days: int,
    max_messages: int = 2000,
    max_topics: int = 12,
) -> dict:
    """Load only one tenant's inbound messages and produce read-only suggestions."""

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    rows = db.query(Message).join(
        Conversation, Conversation.id == Message.conversation_id,
    ).filter(
        Conversation.business_id == business_id,
        Message.direction == "inbound",
        Message.received_at >= since,
    ).order_by(Message.received_at.desc(), Message.id.desc()).limit(max_messages).all()
    result = discover_topic_suggestions(rows, max_topics=max_topics)
    return {"period_days": days, **result}
