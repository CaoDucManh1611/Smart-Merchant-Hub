"""Gemini dense + BM25 retrieval, Reciprocal Rank Fusion, then personalized PageRank."""

import logging
import json
import math
import re
import time
import unicodedata
from collections.abc import Mapping
from collections import defaultdict
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace

from sqlalchemy import inspect as sa_inspect, text as sa_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.embedder import embed_query, _validate_vectors
from app.rag.catalog_filters import (
    catalog_hard_filter_sql,
    canonical_attribute_key,
    extract_query_hard_filters,
    validate_hard_filters,
)
from app.rag.run_logger import query_metadata
from app.rag.topics import TOPIC_TERMS, infer_query_topic, topic_matches, topic_term_matches
from app.rag.topics import fold_topic_text
from app.rag.lexical import STOP_WORDS, contains, identifiers, query_terms

logger = logging.getLogger(__name__)

_SKU_VARIANT_LABELS = {
    "basic", "compact", "full", "large", "left", "lite", "max", "mini",
    "premium", "pro", "plus", "right", "small", "standard", "trai", "phai", "xl", "xxl",
}
def _catalog_filter_sql(
    db,
    hard_filters: Mapping[str, object] | None,
    *,
    chunk_id_expression: str,
    chunk_content_expression: str,
    preserve_policy_sources: bool = False,
    allow_unmapped_lexical_sku: bool = False,
) -> tuple[str, dict[str, object]]:
    bind = getattr(db, "bind", None)
    if bind is None and callable(getattr(db, "get_bind", None)):
        try:
            bind = db.get_bind()
        except Exception:
            bind = None
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "postgresql")
    if hard_filters:
        try:
            inspector = sa_inspect(bind)
            has_mapping_schema = (
                inspector.has_table("recommendation_catalog_chunk_mappings")
                and inspector.has_table("recommendation_catalog_entries")
            )
            if hard_filters.get("required_attributes"):
                has_mapping_schema = has_mapping_schema and inspector.has_table(
                    "recommendation_catalog_attributes"
                )
        except Exception:
            has_mapping_schema = False
        if not has_mapping_schema:
            # Legacy tenant schemas can lack the catalog-to-chunk migration.
            # Lexical results remain tenant-scoped and SKU constrained in the
            # query/content path, then recommendation serving maps them only to
            # products owned by this business. Never pretend structured
            # attributes were enforced when their tables are absent.
            if (
                allow_unmapped_lexical_sku
                and hard_filters.get("object_type") in (None, "product")
                and not hard_filters.get("required_attributes")
            ):
                logger.warning(
                    "catalog hard-filter mapping unavailable; using tenant-scoped legacy lexical retrieval"
                )
                return "", {}
            logger.warning(
                "catalog hard-filter mapping unavailable; refusing unverified filtered retrieval"
            )
            return " AND FALSE", {}
    return catalog_hard_filter_sql(
        hard_filters,
        chunk_id_expression=chunk_id_expression,
        chunk_content_expression=chunk_content_expression,
        chunk_metadata_expression=chunk_id_expression.replace(".id", ".metadata"),
        preserve_policy_sources=preserve_policy_sources,
        allow_unmapped_lexical_sku=allow_unmapped_lexical_sku,
        dialect_name=dialect_name,
    )


def _vector_dimension_error(error: Exception) -> bool:
    message = str(error).casefold()
    return "dimension" in message and any(
        marker in message for marker in ("vector", "expected", "different")
    )


def _query_sku_identifiers(
    query: str,
    hard_filters: Mapping[str, object] | None = None,
) -> list[str]:
    """Treat labelled or SKU-shaped codes as exact IDs, not product specs."""
    filters = hard_filters if isinstance(hard_filters, Mapping) else extract_query_hard_filters(query)
    attributes = filters.get("required_attributes") or {}
    constrained_values: set[str] = set()
    if isinstance(attributes, Mapping):
        for value in attributes.values():
            values = value if isinstance(value, (list, tuple, set, frozenset)) else (value,)
            constrained_values.update(
                re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", str(item)).casefold())
                for item in values
            )
    labelled_skus = {
        match.group(1).casefold()
        for match in re.finditer(
            r"\b(?:sku|mã(?:\s+(?:sản phẩm|hàng))?|ma(?:\s+(?:san pham|hang))?|code|product\s+id|item\s+id)"
            r"\s*[:#]?\s*([\w]+(?:[-_][\w]+)+)",
            query,
            re.IGNORECASE,
        )
    }
    return [
        identifier for identifier in identifiers(query)
        if (
            identifier in labelled_skus
            or identifier.count("-") + identifier.count("_") >= 2
            # Recognize compact model codes such as T-900 without treating
            # specifications like 10W-40 as exact product identifiers.
            or re.fullmatch(r"[a-z]{1,5}[-_]\d{2,}[a-z0-9]*", identifier, re.IGNORECASE)
        )
        if re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", identifier).casefold())
        not in constrained_values
    ]


def _sku_variant_companion_query(query: str, sku_codes: list[str]) -> str | None:
    """Return a bounded same-tenant comparison query for an explicit SKU question.

    The exact-SKU retrieval remains the primary result. This companion query is
    only used when the customer also asks about a variant/comparison, and SKU
    tokens such as ``MINI`` are removed so they do not become accidental AND
    requirements for the comparison product.
    """
    if len(sku_codes) != 1:
        return None
    dash_map = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})
    companion = unicodedata.normalize("NFKC", str(query or "")).translate(dash_map)
    sku_variant_terms: set[str] = set()
    for sku in sku_codes:
        normalized_sku = unicodedata.normalize("NFKC", str(sku)).translate(dash_map).casefold()
        for part in re.split(r"[-_]", normalized_sku):
            if part in _SKU_VARIANT_LABELS:
                sku_variant_terms.add(part)
        companion = re.sub(
            r"(?<![\w])" + re.escape(normalized_sku) + r"(?![\w])",
            " ", companion, flags=re.IGNORECASE,
        )
    companion = re.sub(
        r"\b(?:sku|code|product\s+id|item\s+id|mã(?:\s+(?:sản phẩm|hàng))?)\b\s*[:#]?",
        " ", companion, flags=re.IGNORECASE,
    )
    # A variant embedded in the exact identifier is already represented by
    # that primary hit; it must not hide its counterpart from this query.
    for label in sku_variant_terms:
        companion = re.sub(r"\b" + re.escape(label) + r"\b", " ", companion, flags=re.IGNORECASE)
    companion = " ".join(companion.split())
    folded = fold_topic_text(companion)
    variant_terms = set(folded.split()) & _SKU_VARIANT_LABELS
    mentions_counterpart = bool(variant_terms - sku_variant_terms)
    if not companion or not mentions_counterpart:
        return None
    return companion


def _has_exact_sku_evidence(chunks: list["RetrievedChunk"], sku_codes: list[str]) -> bool:
    """Avoid broadening an unknown SKU into a plausible but incorrect item."""
    for chunk in chunks:
        metadata = chunk.metadata if isinstance(chunk.metadata, Mapping) else {}
        metadata_sku = str(metadata.get("sku") or "").strip().casefold()
        if metadata_sku and any(metadata_sku == sku.casefold() for sku in sku_codes):
            return True
        content = unicodedata.normalize("NFKC", str(chunk.content or "")).translate(
            str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})
        ).casefold()
        if any(
            re.search(r"(?<![\w-])" + re.escape(sku.casefold()) + r"(?![\w-])", content)
            for sku in sku_codes
        ):
            return True
    return False


def _retrieve_sku_variant_companions(
    *,
    query: str,
    sku_codes: list[str],
    primary_chunks: list["RetrievedChunk"],
    supplied_hard_filters: Mapping[str, object],
    effective_hard_filters: Mapping[str, object],
    db: Session,
    business_id: int,
    query_topic: str | None,
    top_k: int,
    similarity_threshold: float | None,
    preserve_policy_sources: bool,
) -> list["RetrievedChunk"]:
    """Fetch same-tenant comparison evidence without weakening caller filters."""
    if supplied_hard_filters.get("sku") is not None:
        return []
    companion_query = _sku_variant_companion_query(query, sku_codes)
    if not companion_query or not _has_exact_sku_evidence(primary_chunks, sku_codes):
        return []

    companion_filters = dict(effective_hard_filters)
    # This inferred SKU constraint selected the primary item. Remove only that
    # inferred constraint for the explicit comparison lookup; preserve caller
    # constraints, required attributes, object type, and business scope.
    companion_filters.pop("sku", None)
    candidates = _retrieve_lexical(
        companion_query,
        db,
        max(top_k * 2, top_k),
        business_id=business_id,
        query_topic=query_topic,
        hard_filters=companion_filters,
        preserve_policy_sources=preserve_policy_sources,
        similarity_threshold=similarity_threshold,
    )
    primary_ids = {item.chunk_id for item in primary_chunks}
    sku_variant_terms = {
        part
        for part in re.split(r"[-_]", unicodedata.normalize("NFKC", sku_codes[0]).casefold())
        if part in _SKU_VARIANT_LABELS
    }
    requested_variants = set(fold_topic_text(companion_query).split()) & _SKU_VARIANT_LABELS
    requested_variants -= sku_variant_terms
    matching_candidates = []
    for item in candidates:
        if item.chunk_id in primary_ids:
            continue
        content_terms = set(fold_topic_text(item.content).split())
        if requested_variants and not content_terms.intersection(requested_variants):
            continue
        matching_candidates.append(item)
    return matching_candidates[:max(top_k, 1)]


def _append_comparison_evidence(
    results: list["RetrievedChunk"],
    companions: list["RetrievedChunk"],
    sku_codes: list[str],
    top_k: int,
) -> list["RetrievedChunk"]:
    """Keep the exact SKU first, then add a bounded comparison candidate."""
    if not companions:
        return results
    combined = list(results)
    seen = {item.chunk_id for item in combined}
    for companion in companions:
        if companion.chunk_id in seen:
            continue
        if len(combined) >= max(top_k, 1):
            # Preserve an exact SKU hit even when the original retrieval filled
            # top-k with nearby chunks.
            exact_index = next(
                (index for index, item in enumerate(combined)
                 if _has_exact_sku_evidence([item], sku_codes)),
                None,
            )
            removable = next(
                (index for index in range(len(combined) - 1, -1, -1)
                 if index != exact_index),
                None,
            )
            if removable is None:
                break
            combined.pop(removable)
        combined.append(companion)
        seen.add(companion.chunk_id)
    return combined


def _lexical_sku_identifiers(
    query: str,
    hard_filters: Mapping[str, object] | None,
) -> list[str]:
    """Use the validated exact SKU filter when present; caller constraints win."""
    sku_filter = hard_filters.get("sku") if isinstance(hard_filters, Mapping) else None
    if sku_filter is not None:
        values = sku_filter if isinstance(sku_filter, (list, tuple, set, frozenset)) else [sku_filter]
        return list(dict.fromkeys(str(value).strip().casefold() for value in values if str(value).strip()))
    return _query_sku_identifiers(query, hard_filters)


def _merge_hard_filters(
    query_filters: Mapping[str, object],
    supplied_filters: Mapping[str, object],
    query_skus: list[str],
) -> tuple[dict[str, object], list[str]]:
    """Keep caller-validated constraints authoritative; infer only missing ones."""
    effective: dict[str, object] = dict(supplied_filters)
    conflicts: list[str] = []

    query_attributes = query_filters.get("required_attributes")
    if isinstance(query_attributes, Mapping):
        attributes = dict(effective.get("required_attributes") or {})
        for key, value in query_attributes.items():
            canonical_key = canonical_attribute_key(str(key))
            if canonical_key in attributes:
                if fold_topic_text(attributes[canonical_key]) != fold_topic_text(value):
                    conflicts.append(f"attribute:{canonical_key}")
                continue
            attributes[canonical_key] = value
        if attributes:
            effective["required_attributes"] = attributes

    for key, value in query_filters.items():
        if key == "required_attributes":
            continue
        if key in effective:
            if fold_topic_text(effective[key]) != fold_topic_text(value):
                conflicts.append(key)
            continue
        effective[key] = value

    if query_skus:
        supplied_sku = effective.get("sku")
        if supplied_sku is None:
            effective["sku"] = query_skus
        else:
            supplied_values = supplied_sku if isinstance(supplied_sku, (list, tuple, set, frozenset)) else [supplied_sku]
            normalized_supplied = {fold_topic_text(value) for value in supplied_values}
            if not normalized_supplied.intersection(fold_topic_text(value) for value in query_skus):
                conflicts.append("sku")

    return validate_hard_filters(effective), sorted(set(conflicts))


def _select_retrieval_mode(
    requested_mode: str,
    hard_filters: Mapping[str, object],
    query_skus: list[str],
    lexical_results: list["RetrievedChunk"],
) -> tuple[str, str]:
    """Keep exact lookups lexical; spend on vectors only when BM25 is weak."""
    if requested_mode != "auto":
        return requested_mode, "configured_mode"
    if hard_filters or query_skus:
        return "bm25", "exact_identifier_or_hard_filter"
    best_lexical_score = max(
        (float(item.similarity or 0.0) for item in lexical_results),
        default=0.0,
    )
    if not lexical_results or best_lexical_score < 0.45:
        return "hybrid", "weak_lexical_candidates"
    return "bm25", "lexical_candidates_sufficient"


def _reranker_diagnostic_name(enable_ppr: bool, enable_mmr: bool) -> str:
    names = []
    if enable_ppr:
        names.append("personalized_pagerank_offline")
    if enable_mmr:
        names.append("lexical_mmr_experimental_v1")
    return "+".join(names) or "none"


def _retrieval_version(
    selected_mode: str,
    ppr_enabled: bool,
    enable_mmr: bool,
    *,
    fallback: bool = False,
) -> str:
    if fallback:
        name = "bm25_fallback"
    elif selected_mode == "hybrid":
        name = "gemini_bm25_rrf"
    else:
        name = "bm25"
    if ppr_enabled:
        name += "_ppr_offline"
    elif not fallback and selected_mode != "hybrid":
        name += "_baseline"
    if enable_mmr:
        name += "_lexical_mmr_experimental"
    return f"{name}_v1"


def _retry_retrieval_mode(requested_mode: str, diagnostics: Mapping[str, object] | None) -> str:
    """Keep a corrective retry on the same score scale as its first retrieval."""
    selected = str((diagnostics or {}).get("retrieval_mode") or "").casefold()
    if selected == "lexical":  # embedding/vector fallback is lexical BM25
        return "bm25"
    if selected in {"bm25", "hybrid"}:
        return selected
    requested = str(requested_mode or "").casefold()
    return requested if requested in {"bm25", "hybrid"} else "bm25"


def _query_mentions_policy_sources(query: str) -> bool:
    folded = fold_topic_text(query)
    policy_topics = ("returns", "delivery", "payments", "shop", "faq")
    return any(
        topic_term_matches(folded, term)
        for topic in policy_topics
        for term in TOPIC_TERMS[topic]
    )


def _should_preserve_policy_sources(query: str, query_topic: str | None) -> bool:
    return query_topic in {"returns", "delivery", "payments", "faq", "shop"} or (
        _query_mentions_policy_sources(query)
    )

_LEXICAL_PRODUCT_METADATA_FIELDS = (
    "category", "category_name", "product_category", "danh_muc", "product_type",
    "product_group", "brand", "brand_name", "manufacturer", "thuong_hieu",
    "model", "model_name", "compatible_with", "compatible_models", "compatibility",
    "vehicle_compatibility", "fitment", "suitable_for", "use_case", "usage",
    "service_type", "tags", "keywords", "aliases", "search_terms", "color", "colors",
    "size", "sizes", "style", "collection", "material", "features", "specs",
    "specifications", "attributes", "product_attributes", "dietary", "ingredients",
    "allergens", "skin_type", "expiry", "storage",
)
_PRESERVED_POLICY_TOPICS = frozenset({"returns", "delivery", "payments", "faq", "shop"})

_LEXICAL_MINIMUM_SIMILARITY = 0.2
_RRF_K = 60
_PPR_DAMPING = 0.85
_PPR_MAX_ITERATIONS = 20
_PPR_TOLERANCE = 1e-10
_PPR_CUSTOMER_BLEND = 0.15

_STOP_WORDS = {
    "bao", "bên", "bạn", "có", "cho", "của", "giá", "gì", "hỏi",
    "không", "là", "nào", "như", "nhiêu", "sản", "phẩm", "thế",
    "vậy", "vị", "với", "xin", "về",
}


@dataclass
class RetrievedChunk:
    """Kết quả trả về từ retriever."""

    chunk_id: int
    document_id: int
    content: str
    similarity: float
    metadata: dict | None
    filename: str | None = None
    chunk_index: int | None = None
    ranking_score: float | None = None
    retrieval_scores: dict[str, float | int] = field(default_factory=dict)


def _metadata_dict(value: object) -> dict | None:
    """Normalize JSON metadata returned by SQL text queries across dialects."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    return value if isinstance(value, dict) else None


def _metadata_search_text(metadata: dict | None) -> str:
    if not isinstance(metadata, dict):
        return ""
    values = []
    pending = [metadata.get(key) for key in _LEXICAL_PRODUCT_METADATA_FIELDS]
    while pending and len(values) < 64:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set)):
            pending.extend(value)
        elif isinstance(value, (str, int, float)):
            values.append(str(value))
    return " ".join(values)


def _retrieve_impl(
    query: str,
    db: Session,
    business_id: int,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
    query_embedding: list[float] | None = None,
    diagnostics: dict | None = None,
    hard_filters: Mapping[str, object] | None = None,
    retrieval_mode: str | None = None,
    enable_ppr: bool = False,
    enable_mmr: bool = False,
    timeout_seconds: float | None = None,
) -> list[RetrievedChunk]:
    """
    Tìm các chunks liên quan nhất với query.

    Args:
        query: Câu hỏi của user
        db: SQLAlchemy session
        top_k: Số lượng chunks tối đa trả về
        similarity_threshold: Ngưỡng similarity tối thiểu

    Returns:
        Danh sách RetrievedChunk, sắp xếp theo similarity giảm dần
    """
    query = (query or "").strip()
    requested_mode = str(retrieval_mode or settings.RAG_RETRIEVAL_MODE or "bm25").strip().casefold()
    if requested_mode not in {"bm25", "hybrid", "auto"}:
        logger.warning("Unknown RAG_RETRIEVAL_MODE=%r; falling back to BM25", requested_mode)
        requested_mode = "bm25"
    selected_mode = "bm25" if requested_mode == "auto" else requested_mode
    ppr_enabled = bool(enable_ppr)
    if not query:
        if diagnostics is not None:
            diagnostics.update(
                retrieval_requested_mode=requested_mode,
                retrieval_mode=selected_mode,
                retrieval_routing_reason="empty_query",
                retrieval_fallback_stage=None,
                retrieval_error_type=None,
            )
        return []

    if top_k is None:
        top_k = settings.RAG_TOP_K
    if similarity_threshold is None:
        similarity_threshold = settings.RAG_SIMILARITY_THRESHOLD

    query_topic = infer_query_topic(query)
    preserve_policy_sources = _should_preserve_policy_sources(query, query_topic)
    started = time.perf_counter()

    query_hard_filters = extract_query_hard_filters(query)
    supplied_hard_filters = validate_hard_filters(hard_filters)
    query_skus = _query_sku_identifiers(query, supplied_hard_filters or query_hard_filters)
    effective_hard_filters, filter_conflicts = _merge_hard_filters(
        query_hard_filters, supplied_hard_filters, query_skus,
    )
    required_attributes = effective_hard_filters.get("required_attributes")
    filter_count = int(effective_hard_filters.get("object_type") is not None)
    filter_count += int(effective_hard_filters.get("sku") is not None)
    filter_count += len(required_attributes) if isinstance(required_attributes, Mapping) else 0
    if diagnostics is not None:
        diagnostics.update(
            retrieval_hard_filter_count=filter_count,
            retrieval_hard_filter_keys=sorted(effective_hard_filters),
            retrieval_filter_conflicts=filter_conflicts,
        )

    # Always collect lexical candidates.  They are especially important for
    # product names, SKU codes and documents ingested without embeddings.
    lexical_results = _retrieve_lexical(
        query,
        db,
        max(top_k * 3, top_k),
        business_id=business_id,
        query_topic=query_topic,
        hard_filters=effective_hard_filters,
        preserve_policy_sources=preserve_policy_sources,
        # Lexical coverage is not on the same scale as cosine similarity;
        # keep a separate floor so mixed questions retain every relevant source.
        similarity_threshold=(
            min(similarity_threshold, _LEXICAL_MINIMUM_SIMILARITY)
            if similarity_threshold is not None else None
        ),
    )
    lexical_threshold = (
        min(similarity_threshold, _LEXICAL_MINIMUM_SIMILARITY)
        if similarity_threshold is not None else None
    )
    comparison_chunks = _retrieve_sku_variant_companions(
        query=query,
        sku_codes=query_skus,
        primary_chunks=lexical_results,
        supplied_hard_filters=supplied_hard_filters,
        effective_hard_filters=effective_hard_filters,
        db=db,
        business_id=business_id,
        query_topic=query_topic,
        top_k=top_k,
        similarity_threshold=lexical_threshold,
        preserve_policy_sources=preserve_policy_sources,
    )
    if diagnostics is not None:
        diagnostics.update(
            retrieval_lexical_hits=len(lexical_results),
            retrieval_bm25_hits=len(lexical_results),
            retrieval_sku_companion_hits=len(comparison_chunks),
        )

    selected_mode, routing_reason = _select_retrieval_mode(
        requested_mode,
        effective_hard_filters,
        query_skus,
        lexical_results,
    )
    if diagnostics is not None:
        diagnostics.update(
            retrieval_requested_mode=requested_mode,
            retrieval_mode=selected_mode,
            retrieval_routing_reason=routing_reason,
            retrieval_fallback_stage=None,
            retrieval_error_type=None,
            retrieval_fusion="rrf" if selected_mode == "hybrid" else None,
            retrieval_lexical_method="bm25",
            retrieval_reranker=_reranker_diagnostic_name(ppr_enabled, enable_mmr),
            retrieval_version=_retrieval_version(selected_mode, ppr_enabled, enable_mmr),
        )

    if selected_mode == "bm25":
        lexical_scores = [
            item.ranking_score if item.ranking_score is not None else item.similarity
            for item in lexical_results
        ]
        ranked_lexical = (
            _personalized_pagerank_rerank(lexical_results, lexical_scores)
            if ppr_enabled else lexical_results
        )
        results = _expand_parent_neighbors(
            _select_candidates(
                ranked_lexical, top_k, topic=query_topic, enable_mmr=enable_mmr,
                preserve_policy_sources=preserve_policy_sources,
            ),
            db, business_id, top_k, hard_filters=effective_hard_filters,
            preserve_policy_sources=preserve_policy_sources,
        )
        results = _append_comparison_evidence(results, comparison_chunks, query_skus, top_k)
        if diagnostics is not None:
            diagnostics.update(retrieval_vector_hits=0, retrieval_returned=len(results))
        logger.info(
            "BM25 retrieval complete: topic=%s hits=%d returned=%d duration_ms=%.2f",
            query_topic, len(lexical_results), len(results),
            (time.perf_counter() - started) * 1000,
        )
        return results

    vector_results: list[RetrievedChunk] = []

    # Bước 1: Embed câu hỏi thành vector; nếu hết quota vẫn dùng từ khóa.
    # Keep customer text out of logs; the short fingerprint is enough to
    # correlate a retry without exposing the prompt or personal data.
    query_meta = query_metadata(query)
    logger.info(
        "Embedding query: chars=%s hash=%s",
        query_meta["query_chars"],
        query_meta["query_hash"],
    )
    try:
        query_vector = (_validate_vectors([query_embedding], expected_count=1)[0]
                        if query_embedding is not None else embed_query(
                            query, timeout_seconds=timeout_seconds,
                        ))
    except Exception as error:
        if diagnostics is not None:
            diagnostics.update(
                retrieval_mode="lexical", retrieval_fallback_stage="embedding",
                retrieval_error_type=type(error).__name__, retrieval_fusion=None,
                retrieval_vector_hits=0,
                retrieval_reranker=_reranker_diagnostic_name(ppr_enabled, enable_mmr),
                retrieval_version=_retrieval_version(
                    "bm25", ppr_enabled, enable_mmr, fallback=True,
                ),
            )
        logger.warning(
            "Vector query unavailable; using lexical retrieval: error_type=%s",
            type(error).__name__,
        )
        logger.info(
            "RAG retrieval complete: topic=%s lexical=%d vector=0 returned=%d duration_ms=%.2f",
            query_topic,
            len(lexical_results),
            min(len(lexical_results), top_k),
            (time.perf_counter() - started) * 1000,
        )
        lexical_scores = [
            item.ranking_score if item.ranking_score is not None else item.similarity
            for item in lexical_results
        ]
        ranked_lexical = (
            _personalized_pagerank_rerank(lexical_results, lexical_scores)
            if ppr_enabled else lexical_results
        )
        results = _expand_parent_neighbors(
            _select_candidates(
                ranked_lexical, top_k, topic=query_topic, enable_mmr=enable_mmr,
                preserve_policy_sources=preserve_policy_sources,
            ),
            db, business_id, top_k, hard_filters=effective_hard_filters,
            preserve_policy_sources=preserve_policy_sources,
        )
        return _append_comparison_evidence(results, comparison_chunks, query_skus, top_k)

    # Search pgvector using a bound parameter.  Do not interpolate the vector
    # into SQL even though it currently comes from a trusted provider.
    if diagnostics is not None:
        diagnostics["retrieval_vector_dimension"] = len(query_vector)
    vector_filter_sql, vector_filter_params = _catalog_filter_sql(
        db, effective_hard_filters, chunk_id_expression="dc.id", chunk_content_expression="dc.content",
        preserve_policy_sources=preserve_policy_sources,
    )
    vector_str = "[" + ",".join(f"{float(value):.10g}" for value in query_vector) + "]"
    raw_sql = f"""
        SELECT
            dc.id,
            dc.document_id,
            dc.content,
            dc.metadata AS chunk_metadata,
            d.filename AS source_filename,
            dc.chunk_index,
            1 - (dc.embedding <=> CAST(:query_vector AS vector)) AS similarity
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE d.status = 'ready'
          AND d.business_id = :business_id
          AND dc.embedding IS NOT NULL
          AND 1 - (dc.embedding <=> CAST(:query_vector AS vector)) >= :threshold
          {vector_filter_sql}
        ORDER BY dc.embedding <=> CAST(:query_vector AS vector), dc.id
        LIMIT :top_k
    """

    try:
        begin_nested = getattr(db, "begin_nested", None)
        with begin_nested() if callable(begin_nested) else nullcontext():
            rows = db.execute(
                sa_text(raw_sql),
                {
                    "query_vector": vector_str,
                    "business_id": business_id,
                    "threshold": similarity_threshold,
                    "top_k": max(top_k * 3, top_k),
                    **vector_filter_params,
                },
            ).fetchall()
    except Exception as error:
        if diagnostics is not None:
            dimension_mismatch = _vector_dimension_error(error)
            diagnostic_values = {
                "retrieval_mode": "lexical",
                "retrieval_fallback_stage": "vector_dimension_mismatch" if dimension_mismatch else "vector_search",
                "retrieval_error_type": type(error).__name__,
                "retrieval_dimension_error": dimension_mismatch,
                "retrieval_fusion": None,
                "retrieval_vector_hits": 0,
                "retrieval_reranker": _reranker_diagnostic_name(ppr_enabled, enable_mmr),
                "retrieval_version": _retrieval_version(
                    "bm25", ppr_enabled, enable_mmr, fallback=True,
                ),
            }
            if dimension_mismatch:
                actual_dimension = len(query_vector)
                error_dimensions = [int(value) for value in re.findall(r"\b\d{2,5}\b", str(error))]
                diagnostic_values["retrieval_vector_dimension"] = actual_dimension
                stored_dimension = next((value for value in error_dimensions if value != actual_dimension), None)
                if stored_dimension is not None:
                    diagnostic_values["retrieval_stored_vector_dimension"] = stored_dimension
            diagnostics.update(diagnostic_values)
        logger.warning(
            "pgvector search unavailable; using lexical retrieval: error_type=%s",
            type(error).__name__,
        )
        logger.info(
            "RAG retrieval complete: topic=%s lexical=%d vector=0 returned=%d duration_ms=%.2f",
            query_topic,
            len(lexical_results),
            min(len(lexical_results), top_k),
            (time.perf_counter() - started) * 1000,
        )
        lexical_scores = [
            item.ranking_score if item.ranking_score is not None else item.similarity
            for item in lexical_results
        ]
        ranked_lexical = (
            _personalized_pagerank_rerank(lexical_results, lexical_scores)
            if ppr_enabled else lexical_results
        )
        results = _expand_parent_neighbors(
            _select_candidates(
                ranked_lexical, top_k, topic=query_topic, enable_mmr=enable_mmr,
                preserve_policy_sources=preserve_policy_sources,
            ),
            db, business_id, top_k, hard_filters=effective_hard_filters,
            preserve_policy_sources=preserve_policy_sources,
        )
        return _append_comparison_evidence(results, comparison_chunks, query_skus, top_k)

    vector_results = []
    for row in rows:
        row_data = row._mapping
        vector_results.append(
            RetrievedChunk(
                chunk_id=row_data["id"],
                document_id=row_data["document_id"],
                content=row_data["content"],
                similarity=float(row_data["similarity"]),
                metadata=_metadata_dict(row_data["chunk_metadata"]),
                filename=row_data["source_filename"],
                chunk_index=row_data["chunk_index"],
                retrieval_scores={"vector_score": float(row_data["similarity"])},
            )
        )

    results = _merge_hybrid_results(
        vector_results, lexical_results, top_k, topic=query_topic,
        enable_ppr=ppr_enabled, enable_mmr=enable_mmr,
        preserve_policy_sources=preserve_policy_sources,
    )
    if diagnostics is not None:
        diagnostics.update(
            retrieval_vector_hits=len(vector_results),
            retrieval_lexical_hits=len(lexical_results),
            retrieval_bm25_hits=len(lexical_results),
        )

    logger.info(
        "Retrieved %d chunks (top_k=%d, threshold=%.2f, topic=%s, bm25=%d, vector=%d, duration_ms=%.2f)",
        len(results),
        top_k,
        similarity_threshold,
        query_topic,
        len(lexical_results),
        len(vector_results),
        (time.perf_counter() - started) * 1000,
    )

    results = _expand_parent_neighbors(
        results, db, business_id, top_k,
        hard_filters=effective_hard_filters,
        preserve_policy_sources=preserve_policy_sources,
    )
    return _append_comparison_evidence(results, comparison_chunks, query_skus, top_k)


@contextmanager
def _retrieval_statement_timeout(db: Session, timeout_seconds: float | None):
    """Bound PostgreSQL retrieval statements without leaving a changed session setting."""
    bind = getattr(db, "bind", None)
    if bind is None and callable(getattr(db, "get_bind", None)):
        try:
            bind = db.get_bind()
        except Exception:
            bind = None
    if (
        timeout_seconds is None
        or timeout_seconds <= 0
        or getattr(getattr(bind, "dialect", None), "name", None) != "postgresql"
    ):
        yield
        return

    timeout_ms = max(1, int(timeout_seconds * 1000))
    with db.begin_nested():
        connection = db.connection()
        previous = connection.execute(sa_text("SHOW statement_timeout")).scalar_one()
        connection.execute(
            sa_text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{timeout_ms}ms"},
        )
        yield
        connection.execute(
            sa_text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": str(previous)},
        )


def retrieve(
    query: str,
    db: Session,
    business_id: int,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
    query_embedding: list[float] | None = None,
    diagnostics: dict | None = None,
    hard_filters: Mapping[str, object] | None = None,
    retrieval_mode: str | None = None,
    enable_ppr: bool = False,
    enable_mmr: bool = False,
    timeout_seconds: float | None = None,
) -> list[RetrievedChunk]:
    """Retrieve with optional provider and PostgreSQL statement timeouts."""
    with _retrieval_statement_timeout(db, timeout_seconds):
        return _retrieve_impl(
            query=query,
            db=db,
            business_id=business_id,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            query_embedding=query_embedding,
            diagnostics=diagnostics,
            hard_filters=hard_filters,
            retrieval_mode=retrieval_mode,
            enable_ppr=enable_ppr,
            enable_mmr=enable_mmr,
            timeout_seconds=timeout_seconds,
        )


def _is_catalog_product_chunk(item: RetrievedChunk) -> bool:
    """Recognize direct product evidence, not a guide merely mentioning a SKU."""
    if (item.metadata or {}).get("sku"):
        return True
    return bool(re.search(r"(?im)^\s*sku\s*[,|]", item.content))


def _diverse_candidates(
    results: list[RetrievedChunk], top_k: int, *, max_per_document: int = 2,
) -> list[RetrievedChunk]:
    counts, selected, deferred = {}, [], []
    for result in results:
        count = counts.get(result.document_id, 0)
        if count < max_per_document:
            selected.append(result)
            counts[result.document_id] = count + 1
        else:
            deferred.append(result)
    return (selected + deferred)[:top_k]


def _lexical_mmr_candidates(
    results: list[RetrievedChunk], top_k: int, *,
    diversity_weight: float = 0.4, max_per_document: int = 2,
) -> list[RetrievedChunk]:
    """Experimental lexical-MMR over the existing rank; never enabled by default.

    Jaccard token overlap is a cheap redundancy proxy, not semantic similarity.
    Keep the relevance component rank-based so BM25 and cosine/RRF scales are
    never compared directly.
    """
    if top_k <= 0 or not results:
        return []
    if not 0 <= diversity_weight <= 1:
        raise ValueError("diversity_weight must be between 0 and 1")
    candidates = results[:min(len(results), max(top_k, top_k * 4))]
    token_sets = [
        {
            token for token in re.findall(r"[a-z0-9]+", fold_topic_text(item.content or ""))
            if len(token) > 1 and token not in STOP_WORDS
        }
        for item in candidates
    ]

    def overlap(left: int, right: int) -> float:
        union = token_sets[left] | token_sets[right]
        return len(token_sets[left] & token_sets[right]) / len(union) if union else 0.0

    selected: list[int] = []
    document_counts: dict[int, int] = defaultdict(int)
    remaining = set(range(len(candidates)))
    while remaining and len(selected) < top_k:
        eligible = [
            index for index in remaining
            if document_counts[candidates[index].document_id] < max_per_document
        ]
        if not eligible:
            eligible = list(remaining)
        best = max(
            eligible,
            key=lambda index: (
                (1 - diversity_weight) / (index + 1)
                - diversity_weight * max((overlap(index, chosen) for chosen in selected), default=0.0),
                -index,
            ),
        )
        selected.append(best)
        document_counts[candidates[best].document_id] += 1
        remaining.remove(best)
    return [candidates[index] for index in selected]


def _select_candidates(
    results: list[RetrievedChunk], top_k: int, *, topic: str | None,
    enable_mmr: bool, preserve_policy_sources: bool = False,
) -> list[RetrievedChunk]:
    max_per_document = 4 if topic == "products" else 2
    if enable_mmr:
        selected = _lexical_mmr_candidates(
            results, top_k, max_per_document=max_per_document,
        )
    else:
        selected = _diverse_candidates(results, top_k, max_per_document=max_per_document)
    if preserve_policy_sources and top_k > 1 and not any(
        str((item.metadata or {}).get("topic") or "").strip().casefold() in _PRESERVED_POLICY_TOPICS
        for item in selected
    ):
        policy_candidate = next((
            item for item in results
            if str((item.metadata or {}).get("topic") or "").strip().casefold()
            in _PRESERVED_POLICY_TOPICS
        ), None)
        if policy_candidate is not None:
            selected = [*selected[:top_k - 1], policy_candidate]
    return selected


def _personalized_pagerank_rerank(
    items: list[RetrievedChunk],
    base_scores: list[float] | None = None,
    customer_product_weights: dict[str, float] | None = None,
) -> list[RetrievedChunk]:
    """Rerank bounded candidates with query relevance and consented product affinity."""
    if not items:
        return items
    customer_product_weights = customer_product_weights or {}

    raw_scores = base_scores if base_scores is not None else [item.similarity for item in items]
    scores = []
    for score in raw_scores:
        try:
            value = float(score)
        except (TypeError, ValueError):
            value = 0.0
        scores.append(max(0.0, value) if math.isfinite(value) else 0.0)
    total = sum(scores)
    query_prior = (
        [score / total for score in scores]
        if total > 0 else [1 / len(items)] * len(items)
    )

    def annotate_pagerank(ranks: list[float]) -> None:
        ordered = sorted(range(len(items)), key=lambda index: (-ranks[index], index))
        positions = {index: rank for rank, index in enumerate(ordered, start=1)}
        for index, item in enumerate(items):
            item.retrieval_scores = {
                **(item.retrieval_scores or {}),
                "ppr_score": float(ranks[index]),
                "ppr_rank": positions[index],
            }

    if len(items) < 2:
        annotate_pagerank(query_prior)
        return items
    personalized_matches: list[tuple[str | None, float]] = []
    product_chunk_counts: dict[str, int] = defaultdict(int)
    for item in items:
        metadata = item.metadata or {}
        keys = []
        if metadata.get("product_id") is not None:
            keys.append(f"id:{metadata['product_id']}")
        if metadata.get("sku"):
            keys.append(f"sku:{str(metadata['sku']).strip().casefold()}")
        key = max(keys, key=lambda candidate: customer_product_weights.get(candidate, 0.0), default=None)
        score = float(customer_product_weights.get(key, 0.0)) if key is not None else 0.0
        personalized_matches.append((key, score))
        if key is not None and score > 0:
            product_chunk_counts[key] += 1
    personalized_scores = [
        score / product_chunk_counts[key] if key is not None and product_chunk_counts.get(key) else 0.0
        for key, score in personalized_matches
    ]
    customer_total = sum(personalized_scores)
    if customer_total > 0:
        customer_prior = [score / customer_total for score in personalized_scores]
        personalization = [
            (1 - _PPR_CUSTOMER_BLEND) * query_score + _PPR_CUSTOMER_BLEND * customer_score
            for query_score, customer_score in zip(query_prior, customer_prior)
        ]
    else:
        personalization = query_prior

    edges: list[dict[int, float]] = [defaultdict(float) for _ in items]

    def connect_bucket(groups: dict[object, list[int]], weight: float) -> None:
        # ponytail: pairwise links stay bounded to top-k candidates (max 120);
        # switch to sparse edges if that cap grows.
        for nodes in groups.values():
            for position, left in enumerate(nodes):
                for right in nodes[position + 1:]:
                    edges[left][right] += weight
                    edges[right][left] += weight

    by_product: dict[object, list[int]] = defaultdict(list)
    by_parent: dict[object, list[int]] = defaultdict(list)
    by_document_index: dict[object, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for index, item in enumerate(items):
        metadata = item.metadata or {}
        for key in ("product_id", "sku"):
            value = metadata.get(key)
            if value is not None and str(value).strip():
                by_product[(key, str(value).strip().casefold())].append(index)
        parent_id = metadata.get("parent_id")
        if parent_id is not None:
            by_parent[(item.document_id, str(parent_id))].append(index)
        if item.chunk_index is not None:
            by_document_index[item.document_id][int(item.chunk_index)].append(index)

    connect_bucket(by_product, 3.0)
    connect_bucket(by_parent, 2.0)
    for document_chunks in by_document_index.values():
        for chunk_index, left_nodes in document_chunks.items():
            for left in left_nodes:
                for right in document_chunks.get(chunk_index + 1, ()):
                    edges[left][right] += 0.35
                    edges[right][left] += 0.35

    if not any(edges) and customer_total <= 0:
        annotate_pagerank(personalization)
        return items

    ranks = personalization[:]
    for _ in range(_PPR_MAX_ITERATIONS):
        updated = [(1 - _PPR_DAMPING) * score for score in personalization]
        dangling_mass = 0.0
        for source, neighbors in enumerate(edges):
            total_weight = sum(neighbors.values())
            if total_weight <= 0:
                dangling_mass += ranks[source]
                continue
            contribution = _PPR_DAMPING * ranks[source] / total_weight
            for target, weight in neighbors.items():
                updated[target] += contribution * weight
        for index, score in enumerate(personalization):
            updated[index] += _PPR_DAMPING * dangling_mass * score
        if sum(abs(new - old) for new, old in zip(updated, ranks)) < _PPR_TOLERANCE:
            ranks = updated
            break
        ranks = updated

    annotate_pagerank(ranks)
    return [
        item for index, item in sorted(
            enumerate(items), key=lambda pair: (-ranks[pair[0]], pair[0])
        )
    ]


def _expand_parent_neighbors(
    results: list[RetrievedChunk], db: Session, business_id: int, top_k: int,
    *, hard_filters: Mapping[str, object] | None = None,
    preserve_policy_sources: bool = False,
) -> list[RetrievedChunk]:
    """Expand bounded source parents while preserving independently ranked hits."""
    if not results:
        return results
    if any("parent_start" in (item.metadata or {}) for item in results):
        expanded = []
        covered: set[tuple[int, int]] = set()
        remaining_context = 12000
        for lead in results[:top_k]:
            if (lead.document_id, lead.chunk_id) in covered:
                continue
            metadata = lead.metadata or {}
            start, end = metadata.get("parent_start"), metadata.get("parent_end")
            if (type(start) is not int or type(end) is not int or lead.chunk_index is None
                    or not 0 <= start <= lead.chunk_index <= end or metadata.get("parent_id") is None):
                expanded.append(lead)
                continue
            whole_parent = end - start < 16
            if not whole_parent:
                start, end = max(start, lead.chunk_index - 1), min(end, lead.chunk_index + 1)
            filter_sql, filter_params = _catalog_filter_sql(
                db, hard_filters, chunk_id_expression="dc.id", chunk_content_expression="dc.content",
                preserve_policy_sources=preserve_policy_sources,
            )
            try:
                begin_nested = getattr(db, "begin_nested", None)
                with begin_nested() if callable(begin_nested) else nullcontext():
                    rows = db.execute(sa_text(f"""
                        SELECT dc.id, dc.document_id, dc.content, dc.metadata AS chunk_metadata,
                               d.filename AS source_filename, dc.chunk_index
                        FROM document_chunks dc JOIN documents d ON d.id = dc.document_id
                        WHERE d.status = 'ready' AND d.business_id = :business_id
                          AND d.id = :document_id AND dc.chunk_index BETWEEN :start_index AND :end_index
                          {filter_sql}
                        ORDER BY dc.chunk_index LIMIT 16
                    """), {"business_id": business_id, "document_id": lead.document_id,
                            "start_index": start, "end_index": end, **filter_params}).fetchall()
            except Exception as error:
                logger.warning("Parent retrieval unavailable: %s", type(error).__name__)
                expanded.append(lead)
                continue
            evidence = {lead.chunk_index: (lead.chunk_id, lead.content)}
            evidence_metadata = {lead.chunk_index: metadata}
            for row in rows:
                data = row._mapping
                row_metadata = _metadata_dict(data["chunk_metadata"]) or {}
                if (data["document_id"] == lead.document_id
                        and row_metadata.get("parent_id") == metadata["parent_id"]
                        and start <= data["chunk_index"] <= end):
                    evidence[data["chunk_index"]] = (data["id"], data["content"])
                    evidence_metadata[data["chunk_index"]] = row_metadata
            budget = min(6000, remaining_context + len(lead.content))
            content = "\n\n".join(evidence[i][1] for i in sorted(evidence))
            complete = whole_parent and sorted(evidence) == list(range(start, end + 1))
            if len(content) > budget or not complete:
                selected = {lead.chunk_index: evidence[lead.chunk_index]}
                size = len(lead.content)
                for index in (lead.chunk_index - 1, lead.chunk_index + 1):
                    if index in evidence and size + len(evidence[index][1]) + 2 <= budget:
                        selected[index] = evidence[index]
                        size += len(evidence[index][1]) + 2
                evidence = selected
                evidence_metadata = {
                    index: evidence_metadata[index] for index in evidence
                    if index in evidence_metadata
                }
                content = "\n\n".join(evidence[i][1] for i in sorted(evidence))
                complete = False
            ids = [evidence[i][0] for i in sorted(evidence)]
            remaining_context -= max(0, len(content) - len(lead.content))
            covered.update((lead.document_id, chunk_id) for chunk_id in ids)
            page_starts = [
                page for page_metadata in evidence_metadata.values()
                if type(page := page_metadata.get("page_start")) is int
            ]
            page_ends = [
                page for page_metadata in evidence_metadata.values()
                if type(page := page_metadata.get("page_end")) is int
            ]
            expanded_metadata = {
                **metadata,
                "expanded_chunk_ids": ids,
                "retrieval_context": "parent" if complete else "neighbors",
            }
            if page_starts:
                expanded_metadata["page_start"] = min(page_starts)
                expanded_metadata["page_end"] = max(page_ends or page_starts)
            expanded.append(replace(lead, content=content, metadata=expanded_metadata))
        return expanded
    if top_k < 2:
        return results
    lead = results[0]
    parent_id = (lead.metadata or {}).get("parent_id")
    if parent_id is None or lead.chunk_index is None:
        return results  # legacy chunks have no structural parent
    filter_sql, filter_params = _catalog_filter_sql(
        db, hard_filters, chunk_id_expression="dc.id", chunk_content_expression="dc.content",
        preserve_policy_sources=preserve_policy_sources,
    )
    try:
        rows = db.execute(sa_text(f"""
            SELECT dc.id, dc.document_id, dc.content, dc.metadata AS chunk_metadata,
                   d.filename AS source_filename, dc.chunk_index
            FROM document_chunks dc JOIN documents d ON d.id = dc.document_id
            WHERE d.status = 'ready' AND d.business_id = :business_id
              AND d.id = :document_id
              AND dc.chunk_index IN (:previous_index, :next_index)
              {filter_sql}
            ORDER BY dc.chunk_index
        """), {
            "business_id": business_id,
            "document_id": lead.document_id,
            "previous_index": lead.chunk_index - 1,
            "next_index": lead.chunk_index + 1,
            **filter_params,
        }).fetchall()
    except Exception as error:
        logger.warning("Parent neighbor lookup unavailable: %s", type(error).__name__)
        return results
    seen = {item.chunk_id for item in results}
    neighbors = []
    for row in rows:
        data = row._mapping
        metadata = _metadata_dict(data["chunk_metadata"]) or {}
        if metadata.get("parent_id") != parent_id or data["id"] in seen:
            continue
        neighbors.append(RetrievedChunk(
            chunk_id=data["id"], document_id=data["document_id"],
            content=data["content"], similarity=lead.similarity,
            metadata=metadata, filename=data["source_filename"],
            chunk_index=data["chunk_index"],
        ))
    expanded_results = (results[:1] + neighbors + results[1:])[:top_k]
    if preserve_policy_sources and top_k > 1 and not any(
        str((item.metadata or {}).get("topic") or "").strip().casefold() in _PRESERVED_POLICY_TOPICS
        for item in expanded_results
    ):
        policy_candidate = next((
            item for item in results
            if str((item.metadata or {}).get("topic") or "").strip().casefold()
            in _PRESERVED_POLICY_TOPICS
        ), None)
        if policy_candidate is not None:
            expanded_results = [*expanded_results[:top_k - 1], policy_candidate]
    return expanded_results


def _merge_hybrid_results(
    vector_results: list[RetrievedChunk],
    lexical_results: list[RetrievedChunk],
    top_k: int,
    topic: str | None = None,
    customer_product_weights: dict[str, float] | None = None,
    *,
    enable_ppr: bool = False,
    enable_mmr: bool = False,
    preserve_policy_sources: bool = False,
) -> list[RetrievedChunk]:
    """Fuse dense/BM25 candidates; PPR is an explicit offline-only ablation."""
    merged: dict[int, tuple[RetrievedChunk, float]] = {}
    topic_step = 1 / (_RRF_K + 1) - 1 / (_RRF_K + 2)

    for candidates, lexical in ((vector_results, False), (lexical_results, True)):
        ranked_candidates = sorted(
            candidates,
            key=lambda item: (
                -(item.ranking_score if lexical and item.ranking_score is not None else item.similarity),
                -item.similarity,
                item.chunk_id,
            ),
        )
        for rank, item in enumerate(ranked_candidates, start=1):
            score = 1 / (_RRF_K + rank)
            features = dict(item.retrieval_scores or {})
            if lexical:
                features.update(
                    bm25_score=float(item.ranking_score if item.ranking_score is not None else 0.0),
                    bm25_rank=rank,
                )
            else:
                features.update(vector_score=float(item.similarity), vector_rank=rank)
            features["rrf_score"] = float(features.get("rrf_score", 0.0)) + score
            item.retrieval_scores = features
            existing = merged.get(item.chunk_id)
            if existing is None:
                merged[item.chunk_id] = (item, score)
                continue
            current_item, current_score = existing
            current_features = dict(current_item.retrieval_scores or {})
            for name, value in (item.retrieval_scores or {}).items():
                if name != "rrf_score":
                    current_features[name] = value
            current_features["rrf_score"] = float(current_features.get("rrf_score", 0.0)) + score
            current_item.retrieval_scores = current_features
            current_item.similarity = max(current_item.similarity, item.similarity)
            if item.ranking_score is not None:
                current_item.ranking_score = item.ranking_score
            merged[item.chunk_id] = (current_item, current_score + score)

    for chunk_id, (item, score) in list(merged.items()):
        if topic_matches(item.metadata, topic):
            score += topic_step
        if topic == "products" and _is_catalog_product_chunk(item):
            score += 2 * topic_step
        item.retrieval_scores = {
            **(item.retrieval_scores or {}),
            "rrf_adjusted_score": float(score),
        }
        merged[chunk_id] = (item, score)

    ranked = sorted(merged.values(), key=lambda pair: (-pair[1], pair[0].chunk_id))
    for rank, (item, _score) in enumerate(ranked, start=1):
        item.retrieval_scores = {**(item.retrieval_scores or {}), "rrf_rank": rank}
    ranked_items = [item for item, _score in ranked]
    if enable_ppr:
        for item, score in ranked:
            item.retrieval_scores = {**(item.retrieval_scores or {}), "ppr_input_score": float(score)}
        reranked = _personalized_pagerank_rerank(
            ranked_items,
            [score for _item, score in ranked],
            customer_product_weights,
        )
    else:
        reranked = ranked_items
    return _select_candidates(
        reranked, top_k, topic=topic, enable_mmr=enable_mmr,
        preserve_policy_sources=preserve_policy_sources,
    )


def _retrieve_lexical(
    query: str,
    db: Session,
    top_k: int,
    business_id: int,
    query_topic: str | None = None,
    similarity_threshold: float | None = None,
    hard_filters: Mapping[str, object] | None = None,
    preserve_policy_sources: bool = False,
) -> list[RetrievedChunk]:
    """Generate tenant-scoped lexical candidates and rank them with BM25."""
    sku_codes = _lexical_sku_identifiers(query, hard_filters)
    terms = query_terms(query)
    # A preference is useful for selecting matching products, but generic
    # preference guidelines are not evidence that a particular item is stocked.
    if query_topic == "products" and len(terms) > 1:
        terms = [aliases for aliases in terms if aliases[0] != "preference"]
    if not terms and not sku_codes:
        return []

    # ponytail: BM25 is computed in Python over the tenant-scoped candidate pool
    # (max(200, top_k * 40)); move corpus statistics to indexed PostgreSQL search
    # if retrieval evaluation shows recall loss as a shop's knowledge base grows.
    params = {"business_id": business_id, "candidate_limit": max(200, top_k * 40)}
    filter_sql, filter_params = _catalog_filter_sql(
        db, hard_filters, chunk_id_expression="dc.id", chunk_content_expression="dc.content",
        preserve_policy_sources=preserve_policy_sources, allow_unmapped_lexical_sku=True,
    )
    params.update(filter_params)
    dialect = getattr(getattr(db, "bind", None), "dialect", None)
    if getattr(dialect, "name", "") == "sqlite":
        # SQLite QA uses the same folding function as production ranking.
        db.connection().connection.driver_connection.create_function("rag_fold", 1, fold_topic_text)
        metadata_fields = " || ' ' || ".join(
            f"COALESCE(CAST(json_extract(dc.metadata, '$.{field}') AS TEXT), '')"
            for field in _LEXICAL_PRODUCT_METADATA_FIELDS
        )
        searchable = (
            "COALESCE(CAST(dc.content AS TEXT), '') || ' ' "
            "|| COALESCE(json_extract(dc.metadata, '$.section'), '') || ' ' "
            "|| COALESCE(json_extract(dc.metadata, '$.context'), '') || ' ' || "
            + metadata_fields
        )
        search_sql = f"rag_fold({searchable})"
    else:
        accents = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
        params["fold_from"] = accents
        params["fold_to"] = "".join(
            "d" if c == "đ" else "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
            for c in accents
        )
        metadata_fields = " || ' ' || ".join(
            f"COALESCE(dc.metadata ->> '{field}', '')"
            for field in _LEXICAL_PRODUCT_METADATA_FIELDS
        )
        searchable = (
            "COALESCE(CAST(dc.content AS TEXT), '') || ' ' "
            "|| COALESCE(dc.metadata ->> 'section', '') || ' ' "
            "|| COALESCE(dc.metadata ->> 'context', '') || ' ' || "
            + metadata_fields
        )
        search_sql = f"REPLACE(REPLACE(translate(LOWER({searchable}), :fold_from, :fold_to), '-', ' '), '/', ' ')"

    normalized_column = search_sql
    search_sql = "sc.search_text"
    conditions = []
    for index, aliases in enumerate(terms):
        alternatives = []
        for alias_index, alias in enumerate(aliases):
            key = f"term_{index}_{alias_index}"
            params[key] = f"%{alias}%"
            alternatives.append(f"{search_sql} LIKE :{key}")
        conditions.append("(" + " OR ".join(alternatives) + ")")
    sku_conditions = []
    for index, sku in enumerate(sku_codes):
        key = f"identifier_{index}"
        params[key] = f"%{sku}%"
        sku_conditions.append(f"LOWER(sc.content) LIKE :{key}")

    mapped_sku_values = hard_filters.get("sku") if hard_filters else None
    mapped_sku_params = []
    if mapped_sku_values is not None:
        values = mapped_sku_values if isinstance(mapped_sku_values, (list, tuple, set, frozenset)) else [mapped_sku_values]
        for index, value in enumerate(sorted({" ".join(unicodedata.normalize("NFKC", str(value)).casefold().split()) for value in values})):
            key = f"lexical_catalog_sku_{index}"
            params[key] = value[:120]
            mapped_sku_params.append(f":{key}")
        mapped_sku_match = (
            "EXISTS (SELECT 1 FROM recommendation_catalog_chunk_mappings rcm_lexical_sku "
            "JOIN recommendation_catalog_entries rce_lexical_sku "
            "ON rce_lexical_sku.id = rcm_lexical_sku.catalog_entry_id "
            "WHERE rcm_lexical_sku.document_chunk_id = dc.id "
            "AND rce_lexical_sku.business_id = :business_id "
            f"AND rce_lexical_sku.sku_norm IN ({', '.join(mapped_sku_params)}))"
        ) if mapped_sku_params else "FALSE"
    else:
        mapped_sku_match = "FALSE"
    mapped_sku_condition = "sc.exact_catalog_sku_match = 1"
    all_conditions = sku_conditions + conditions
    if mapped_sku_params:
        all_conditions.append(mapped_sku_condition)
    match_count = " + ".join(f"CASE WHEN {condition} THEN 1 ELSE 0 END" for condition in conditions) or "0"
    sku_priority_conditions = [*sku_conditions]
    if mapped_sku_params:
        sku_priority_conditions.append(mapped_sku_condition)
    sku_order = (
        "CASE WHEN (" + " OR ".join(sku_priority_conditions) + ") THEN 0 ELSE 1 END, "
    ) if sku_priority_conditions else ""
    rows = db.execute(sa_text(f"""
        WITH scoped AS MATERIALIZED (
            SELECT dc.id, dc.document_id, dc.content, dc.metadata AS chunk_metadata,
                   d.filename AS source_filename, dc.chunk_index,
                   {normalized_column} AS search_text,
                   CASE WHEN {mapped_sku_match} THEN 1 ELSE 0 END AS exact_catalog_sku_match
            FROM document_chunks dc JOIN documents d ON d.id = dc.document_id
            WHERE d.status = 'ready' AND d.business_id = :business_id
              {filter_sql}
        )
        SELECT * FROM scoped sc WHERE ({" OR ".join(all_conditions)})
        ORDER BY {sku_order}({match_count}) DESC, sc.id
        LIMIT :candidate_limit
    """), params).fetchall()

    candidates = []
    for row in rows:
        data = row._mapping
        metadata = _metadata_dict(data["chunk_metadata"]) or {}
        searchable = " ".join((
            data["content"],
            str(metadata.get("section") or ""),
            str(metadata.get("context") or ""),
            _metadata_search_text(metadata),
        ))
        folded = fold_topic_text(searchable)
        matches = [any(contains(folded, alias) for alias in aliases) for aliases in terms]
        exact_sku = bool(data.get("exact_catalog_sku_match")) or any(
            re.search(r"(?<![\w-])" + re.escape(sku) + r"(?![\w-])", data["content"].casefold())
            for sku in sku_codes
        )
        policy_source = (
            preserve_policy_sources
            and str(metadata.get("topic") or "").strip().casefold() in _PRESERVED_POLICY_TOPICS
        )
        if sku_codes and not exact_sku and not policy_source:
            continue
        candidates.append((data, matches, exact_sku))
    # Rare observed concepts weigh more; unmatched concepts get neutral weight
    # so one incidental overlap cannot score like a complete answer.
    weights = []
    for index, aliases in enumerate(terms):
        document_frequency = sum(flags[index] for _, flags, _ in candidates)
        if not document_frequency:
            weights.append(1)
            continue
        weight = 1 + math.log((len(candidates) + 1) / (1 + document_frequency))
        # An exact amount can help rank a policy, but an unlisted requested
        # quantity should not hide the product or policy that covers the rest.
        if len(aliases) == 1 and aliases[0].isdigit():
            weight *= 0.25
        weights.append(weight)
    searchable_documents = []
    for data, _matches, _exact_sku in candidates:
        metadata = _metadata_dict(data["chunk_metadata"]) or {}
        searchable_documents.append(" ".join((
            data["content"], str(metadata.get("section") or ""),
            str(metadata.get("context") or ""),
            _metadata_search_text(metadata),
        )))
    bm25_scores = _bm25_scores(searchable_documents, terms)
    scored = []
    for (data, matches, exact_sku), bm25_score in zip(candidates, bm25_scores):
        coverage = sum(weight for weight, match in zip(weights, matches) if match) / max(sum(weights), 1)
        score = min(0.99, 0.75 * coverage + (0.65 if exact_sku else 0))
        if similarity_threshold is not None and score < similarity_threshold:
            continue
        metadata = _metadata_dict(data["chunk_metadata"])
        chunk = RetrievedChunk(
            chunk_id=data["id"], document_id=data["document_id"],
            content=data["content"], similarity=score, metadata=metadata,
            filename=data["source_filename"], chunk_index=data["chunk_index"],
            ranking_score=bm25_score,
            retrieval_scores={"bm25_score": float(bm25_score)},
        )
        rank = (score + (0.08 if topic_matches(metadata, query_topic) else 0)
                + (0.3 if query_topic == "products" and _is_catalog_product_chunk(chunk) else 0))
        scored.append((bm25_score, rank, chunk))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2].chunk_id))
    return [item for _bm25, _tie_break, item in scored[:top_k]]


def _bm25_scores(
    documents: list[str], query_groups: list[tuple[str, ...]], *, k1: float = 1.5, b: float = 0.75,
) -> list[float]:
    """Score folded Vietnamese/English text with BM25 over a bounded candidate set."""
    if not documents or not query_groups:
        return [0.0] * len(documents)

    folded_documents = [fold_topic_text(document) for document in documents]
    tokenized = [document.split() for document in folded_documents]
    lengths = [len(tokens) for tokens in tokenized]
    average_length = sum(lengths) / max(len(lengths), 1) or 1.0

    frequencies: list[list[int]] = []
    for folded_document in folded_documents:
        padded_document = f" {folded_document} "
        frequencies.append([
            max((padded_document.count(f" {fold_topic_text(alias)} ") for alias in aliases), default=0)
            for aliases in query_groups
        ])

    document_count = len(documents)
    document_frequencies = [
        sum(row[index] > 0 for row in frequencies)
        for index in range(len(query_groups))
    ]
    idf = [
        math.log(1 + (document_count - frequency + 0.5) / (frequency + 0.5))
        for frequency in document_frequencies
    ]
    scores = []
    for length, row in zip(lengths, frequencies):
        score = 0.0
        for term_frequency, inverse_frequency in zip(row, idf):
            if not term_frequency:
                continue
            denominator = term_frequency + k1 * (1 - b + b * length / average_length)
            score += inverse_frequency * term_frequency * (k1 + 1) / denominator
        scores.append(score)
    return scores
