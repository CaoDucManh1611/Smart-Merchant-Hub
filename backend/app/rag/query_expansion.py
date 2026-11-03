"""Bounded, opt-in query expansion helpers for offline or caller-controlled RAG.

This module has no provider or network dependency and is not wired into serving.
The original query and hard filters are always retained exactly as supplied.
Generated variants are supplemental retrieval queries; callers must still apply
the unchanged hard filters to every retrieval branch. ``hypothetical_text`` is
synthetic retrieval material only and must never be treated as source evidence
or cited in an answer.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import unicodedata
from typing import Any, Literal


ExpansionMode = Literal["cheap", "model"]
ExpansionGenerator = Callable[[str], object]

MAX_QUERY_CHARS = 2_000
MAX_QUERY_VARIANTS = 2
MAX_VARIANT_CHARS = 360
MAX_HYPOTHETICAL_TEXT_CHARS = 1_200
MAX_GENERATED_TEXT_CHARS = 1_920
_MAX_VARIANT_CANDIDATES_TO_INSPECT = 8


@dataclass(frozen=True, slots=True)
class QueryExpansionPlan:
    """A safe plan that keeps user constraints separate from generated text.

    ``retrieval_queries`` always starts with the unmodified user query. The
    ``hard_filters`` object is returned by reference and is never passed to the
    generator, copied, or changed here. ``hypothetical_text`` is deliberately
    separate from the retrieval query list and is not citable evidence.
    """

    original_query: str
    hard_filters: Mapping[str, Any] | None
    query_variants: tuple[str, ...]
    hypothetical_text: str | None
    mode: ExpansionMode
    reason: str

    @property
    def retrieval_queries(self) -> tuple[str, ...]:
        """Return the original query followed by supplemental query variants."""
        return (self.original_query, *self.query_variants)

    @property
    def hypothetical_text_is_citable(self) -> bool:
        """Explicitly mark generated HyDE text as unsuitable for citations."""
        return False


def normalize_query_text(value: str) -> str:
    """Normalize generated text with NFC and collapsed whitespace only.

    Meaningful tokens, punctuation, accents, and case are otherwise preserved.
    The user's original query is never passed through this function in the plan.
    """
    return " ".join(unicodedata.normalize("NFC", value).split())


def plan_query_expansion(
    query: str,
    hard_filters: Mapping[str, Any] | None = None,
    *,
    mode: ExpansionMode = "cheap",
    weak_retrieval: bool = False,
    generator: ExpansionGenerator | None = None,
) -> QueryExpansionPlan:
    """Build a bounded supplemental-query plan without changing constraints.

    ``cheap`` is the default and never calls ``generator``. ``model`` is only
    eligible after the caller explicitly reports weak retrieval; it makes at
    most one callback call. The callback receives only the original query and
    may return a mapping with ``query_variants`` (a list/tuple of strings) and
    optional ``hypothetical_text``. Invalid or oversized fields are ignored.

    This helper does not perform retrieval, validate generated claims, or turn
    hypothetical text into evidence. The caller remains responsible for
    enforcing callback timeout, provider privacy and cost/token budget, applying
    ``hard_filters`` unchanged to every retrieval query, and excluding
    hypothetical text from answer citations and source lists.
    """
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    if not isinstance(weak_retrieval, bool):
        raise TypeError("weak_retrieval must be a bool")
    if mode not in ("cheap", "model"):
        raise ValueError("mode must be 'cheap' or 'model'")

    def empty(reason: str) -> QueryExpansionPlan:
        return QueryExpansionPlan(
            original_query=query,
            hard_filters=hard_filters,
            query_variants=(),
            hypothetical_text=None,
            mode=mode,
            reason=reason,
        )

    if mode == "cheap":
        return empty("cheap_mode")
    if not weak_retrieval:
        return empty("retrieval_not_weak")
    if generator is None:
        return empty("generator_unavailable")
    if not query.strip():
        return empty("empty_query")
    if len(query) > MAX_QUERY_CHARS:
        return empty("query_too_long")

    try:
        generated = generator(query)
    except Exception:
        # Expansion is optional: a provider/callback failure must fail closed.
        return empty("generator_error")
    if not isinstance(generated, Mapping):
        return empty("malformed_output")

    variants: list[str] = []
    seen = {normalize_query_text(query).casefold()}
    raw_variants = generated.get("query_variants")
    if isinstance(raw_variants, (list, tuple)):
        for candidate in raw_variants[:_MAX_VARIANT_CANDIDATES_TO_INSPECT]:
            if not isinstance(candidate, str):
                continue
            normalized = normalize_query_text(candidate)
            if not normalized or len(normalized) > MAX_VARIANT_CHARS:
                continue
            dedupe_key = normalized.casefold()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            variants.append(normalized)
            if len(variants) == MAX_QUERY_VARIANTS:
                break

    hypothetical_text: str | None = None
    raw_hypothetical = generated.get("hypothetical_text")
    if isinstance(raw_hypothetical, str):
        normalized_hypothetical = normalize_query_text(raw_hypothetical)
        if normalized_hypothetical and len(normalized_hypothetical) <= MAX_HYPOTHETICAL_TEXT_CHARS:
            hypothetical_text = normalized_hypothetical

    # Individual caps already imply this total bound; keep the aggregate check
    # explicit so later limit changes cannot silently widen the model output.
    generated_chars = sum(map(len, variants)) + len(hypothetical_text or "")
    if generated_chars > MAX_GENERATED_TEXT_CHARS:
        hypothetical_text = None

    reason = "expanded" if variants or hypothetical_text else "no_valid_expansions"
    return QueryExpansionPlan(
        original_query=query,
        hard_filters=hard_filters,
        query_variants=tuple(variants),
        hypothetical_text=hypothetical_text,
        mode=mode,
        reason=reason,
    )
