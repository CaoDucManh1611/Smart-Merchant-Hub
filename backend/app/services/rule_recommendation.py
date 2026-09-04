"""Deterministic, explainable rule suggestion helper.

Suggestions are data only; a human must review them before any workflow is
changed. This keeps early ML experiments reversible and auditable.
"""

from collections.abc import Mapping


def suggest_tag_rule(*, channel: str, sample_size: int, tag: str = "khach moi") -> dict:
    return {
        "title": f"Gắn tag {tag} cho khách {channel.title()}",
        "rationale": f"{sample_size} sự kiện message.created đến từ kênh {channel}; rule này chỉ là gợi ý cần duyệt.",
        "proposed_action": {"type": "add_tag", "tag": tag},
    }


def summarize_rule_evidence(events: Mapping[str, int]) -> str:
    return "; ".join(f"{key}={value}" for key, value in sorted(events.items()))
