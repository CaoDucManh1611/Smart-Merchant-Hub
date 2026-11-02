"""Bounded, tenant-scoped control for optional corrective RAG retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.business_setting import BusinessSetting


@dataclass(frozen=True)
class RagRuntimeOptions:
    retrieval_mode: str
    agentic_mode: str
    max_tool_calls: int
    retry_threshold: float
    timeout_seconds: float

    @property
    def agentic_enabled(self) -> bool:
        return self.agentic_mode != "off"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on", "enabled"}


def load_rag_runtime_options(db: Session, business_id: int) -> RagRuntimeOptions:
    """Load per-shop switches; invalid/missing values safely use app defaults."""
    retrieval_mode = str(settings.RAG_RETRIEVAL_MODE or "bm25").strip().casefold()
    if retrieval_mode not in {"bm25", "hybrid"}:
        retrieval_mode = "bm25"
    agentic_mode = str(getattr(settings, "RAG_AGENTIC_MODE", "off") or "off").strip().casefold()
    if agentic_mode not in {"off", "decision_shadow", "execute_shadow", "active"}:
        agentic_mode = "off"
    if agentic_mode == "off" and bool(getattr(settings, "RAG_AGENTIC_ENABLED", False)):
        agentic_mode = "active"
    max_tool_calls = max(1, min(int(getattr(settings, "RAG_AGENTIC_MAX_TOOL_CALLS", 4)), 4))
    retry_threshold = min(max(float(getattr(settings, "RAG_AGENTIC_RETRY_THRESHOLD", 0.3)), 0.0), 1.0)
    timeout_seconds = max(0.1, min(float(getattr(settings, "RAG_AGENTIC_TIMEOUT_SECONDS", 8.0)), 30.0))
    try:
        rows = db.query(BusinessSetting.key, BusinessSetting.value).filter(
            BusinessSetting.business_id == business_id,
            BusinessSetting.key.in_(
                ("rag_retrieval_mode", "rag_agentic_mode", "rag_agentic_enabled"),
            ),
        ).all()
        values = {str(key): str(value) for key, value in rows}
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
        return RagRuntimeOptions(retrieval_mode, agentic_mode, max_tool_calls, retry_threshold, timeout_seconds)
    requested_mode = values.get("rag_retrieval_mode", "").strip().casefold()
    if requested_mode in {"bm25", "hybrid"}:
        retrieval_mode = requested_mode
    requested_agentic_mode = values.get("rag_agentic_mode", "").strip().casefold()
    if requested_agentic_mode in {"off", "decision_shadow", "execute_shadow", "active"}:
        agentic_mode = requested_agentic_mode
    elif "rag_agentic_enabled" in values:
        agentic_mode = "active" if _truthy(values["rag_agentic_enabled"]) else "off"
    return RagRuntimeOptions(retrieval_mode, agentic_mode, max_tool_calls, retry_threshold, timeout_seconds)


def retrieval_is_weak(chunks, threshold: float) -> bool:
    if not chunks:
        return True
    return max((float(getattr(chunk, "similarity", 0.0) or 0.0) for chunk in chunks), default=0.0) < threshold


def corrective_query(query: str) -> str:
    """Add a small intent-specific vocabulary while preserving every original constraint."""
    folded = unicodedata.normalize("NFKD", str(query or "").casefold()).replace("đ", "d")
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    folded = " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split())
    expansions = (
        (("giao hang", "van chuyen", "shipping", "delivery"), "phí vận chuyển thời gian giao hàng đơn vị giao nhận"),
        (("doi tra", "hoan tien", "refund", "return", "bao hanh", "warranty"), "điều kiện quy trình chính sách đổi trả hoàn tiền bảo hành"),
        (("ton kho", "con hang", "stock", "available"), "tồn khả dụng số lượng còn hàng trạng thái bán"),
        (("gia", "bao nhieu", "price", "cost"), "giá bán giá hiện hành đơn giá"),
        (("dat lich", "lich hen", "appointment", "booking"), "lịch hẹn thời gian dịch vụ đặt lịch"),
    )
    for triggers, terms in expansions:
        if any(trigger in folded for trigger in triggers):
            addition = f" {terms}"
            return (str(query or "").strip() + addition)[:1200]
    return " ".join(str(query or "").split())[:1200]


def evidence_quality(chunks) -> tuple[float, float]:
    """Compare top relevance and top-three mean within the same retrieval mode."""
    scores = []
    for chunk in chunks or []:
        retrieval_scores = getattr(chunk, "retrieval_scores", None) or {}
        score = retrieval_scores.get("rrf_adjusted_score")
        if score is None:
            score = getattr(chunk, "similarity", 0.0)
        try:
            scores.append(float(score))
        except (TypeError, ValueError):
            continue
    scores.sort(reverse=True)
    if not scores:
        return (0.0, 0.0)
    # Scores are ranking signals, not calibrated probabilities.
    return (scores[0], sum(scores[:3]) / min(3, len(scores)))
