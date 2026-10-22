"""Gemini dense + BM25 retrieval, Reciprocal Rank Fusion, then personalized PageRank."""

import logging
import json
import math
import re
import time
import unicodedata
from collections import defaultdict
from contextlib import nullcontext
from dataclasses import dataclass, replace

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.embedder import embed_query, _validate_vectors
from app.rag.run_logger import query_metadata
from app.rag.topics import infer_query_topic, topic_matches
from app.rag.topics import fold_topic_text
from app.rag.lexical import contains, identifiers, query_terms

logger = logging.getLogger(__name__)

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


def _metadata_dict(value: object) -> dict | None:
    """Normalize JSON metadata returned by SQL text queries across dialects."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    return value if isinstance(value, dict) else None


def retrieve(
    query: str,
    db: Session,
    business_id: int,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
    query_embedding: list[float] | None = None,
    diagnostics: dict | None = None,
    customer_product_weights: dict[str, float] | None = None,
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
    if diagnostics is not None:
        diagnostics.update(
            retrieval_mode="hybrid",
            retrieval_fallback_stage=None,
            retrieval_error_type=None,
            retrieval_fusion="rrf",
            retrieval_lexical_method="bm25",
            retrieval_reranker="personalized_pagerank",
        )
    if not query:
        return []

    if top_k is None:
        top_k = settings.RAG_TOP_K
    if similarity_threshold is None:
        similarity_threshold = settings.RAG_SIMILARITY_THRESHOLD

    query_topic = infer_query_topic(query)
    started = time.perf_counter()

    # Always collect lexical candidates.  They are especially important for
    # product names, SKU codes and documents ingested without embeddings.
    lexical_results = _retrieve_lexical(
        query,
        db,
        max(top_k * 3, top_k),
        business_id=business_id,
        query_topic=query_topic,
        # Lexical coverage is not on the same scale as cosine similarity;
        # keep a separate floor so mixed questions retain every relevant source.
        similarity_threshold=(
            min(similarity_threshold, _LEXICAL_MINIMUM_SIMILARITY)
            if similarity_threshold is not None else None
        ),
    )
    if diagnostics is not None:
        diagnostics.update(
            retrieval_lexical_hits=len(lexical_results),
            retrieval_bm25_hits=len(lexical_results),
        )
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
                        if query_embedding is not None else embed_query(query))
    except Exception as error:
        if diagnostics is not None:
            diagnostics.update(retrieval_mode="lexical", retrieval_fallback_stage="embedding",
                               retrieval_error_type=type(error).__name__)
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
        return _expand_parent_neighbors(
            _diverse_candidates(
                _personalized_pagerank_rerank(
                    lexical_results, lexical_scores, customer_product_weights,
                ), top_k,
                max_per_document=4 if query_topic == "products" else 2,
            ),
            db, business_id, top_k,
        )

    # Search pgvector using a bound parameter.  Do not interpolate the vector
    # into SQL even though it currently comes from a trusted provider.
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
                },
            ).fetchall()
    except Exception as error:
        if diagnostics is not None:
            diagnostics.update(retrieval_mode="lexical", retrieval_fallback_stage="vector_search",
                               retrieval_error_type=type(error).__name__)
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
        return _expand_parent_neighbors(
            _diverse_candidates(
                _personalized_pagerank_rerank(
                    lexical_results, lexical_scores, customer_product_weights,
                ), top_k,
                max_per_document=4 if query_topic == "products" else 2,
            ),
            db, business_id, top_k,
        )

    vector_results = []
    for row in rows:
        row_data = row._mapping
        if identifiers(query) and not any(
            re.search(r"(?<![\w-])" + re.escape(sku) + r"(?![\w-])", row_data["content"].casefold())
            for sku in identifiers(query)
        ):
            continue
        vector_results.append(
            RetrievedChunk(
                chunk_id=row_data["id"],
                document_id=row_data["document_id"],
                content=row_data["content"],
                similarity=float(row_data["similarity"]),
                metadata=_metadata_dict(row_data["chunk_metadata"]),
                filename=row_data["source_filename"],
                chunk_index=row_data["chunk_index"],
            )
        )

    results = _merge_hybrid_results(
        vector_results, lexical_results, top_k, topic=query_topic,
        customer_product_weights=customer_product_weights,
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

    return _expand_parent_neighbors(results, db, business_id, top_k)


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


def _personalized_pagerank_rerank(
    items: list[RetrievedChunk],
    base_scores: list[float] | None = None,
    customer_product_weights: dict[str, float] | None = None,
) -> list[RetrievedChunk]:
    """Rerank bounded candidates with query relevance and consented product affinity."""
    if len(items) < 2:
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

    return [
        item for index, item in sorted(
            enumerate(items), key=lambda pair: (-ranks[pair[0]], pair[0])
        )
    ]


def _expand_parent_neighbors(
    results: list[RetrievedChunk], db: Session, business_id: int, top_k: int,
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
            try:
                begin_nested = getattr(db, "begin_nested", None)
                with begin_nested() if callable(begin_nested) else nullcontext():
                    rows = db.execute(sa_text("""
                        SELECT dc.id, dc.document_id, dc.content, dc.metadata AS chunk_metadata,
                               d.filename AS source_filename, dc.chunk_index
                        FROM document_chunks dc JOIN documents d ON d.id = dc.document_id
                        WHERE d.status = 'ready' AND d.business_id = :business_id
                          AND d.id = :document_id AND dc.chunk_index BETWEEN :start_index AND :end_index
                        ORDER BY dc.chunk_index LIMIT 16
                    """), {"business_id": business_id, "document_id": lead.document_id,
                            "start_index": start, "end_index": end}).fetchall()
            except Exception as error:
                logger.warning("Parent retrieval unavailable: %s", type(error).__name__)
                expanded.append(lead)
                continue
            evidence = {lead.chunk_index: (lead.chunk_id, lead.content)}
            for row in rows:
                data = row._mapping
                if (data["document_id"] == lead.document_id
                        and (_metadata_dict(data["chunk_metadata"]) or {}).get("parent_id") == metadata["parent_id"]
                        and start <= data["chunk_index"] <= end):
                    evidence[data["chunk_index"]] = (data["id"], data["content"])
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
                content = "\n\n".join(evidence[i][1] for i in sorted(evidence))
                complete = False
            ids = [evidence[i][0] for i in sorted(evidence)]
            remaining_context -= max(0, len(content) - len(lead.content))
            covered.update((lead.document_id, chunk_id) for chunk_id in ids)
            expanded.append(replace(lead, content=content, metadata={
                **metadata, "expanded_chunk_ids": ids,
                "retrieval_context": "parent" if complete else "neighbors",
            }))
        return expanded
    if top_k < 2:
        return results
    lead = results[0]
    parent_id = (lead.metadata or {}).get("parent_id")
    if parent_id is None or lead.chunk_index is None:
        return results  # legacy chunks have no structural parent
    try:
        rows = db.execute(sa_text("""
            SELECT dc.id, dc.document_id, dc.content, dc.metadata AS chunk_metadata,
                   d.filename AS source_filename, dc.chunk_index
            FROM document_chunks dc JOIN documents d ON d.id = dc.document_id
            WHERE d.status = 'ready' AND d.business_id = :business_id
              AND d.id = :document_id
              AND dc.chunk_index IN (:previous_index, :next_index)
            ORDER BY dc.chunk_index
        """), {
            "business_id": business_id,
            "document_id": lead.document_id,
            "previous_index": lead.chunk_index - 1,
            "next_index": lead.chunk_index + 1,
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
    return (results[:1] + neighbors + results[1:])[:top_k]


def _merge_hybrid_results(
    vector_results: list[RetrievedChunk],
    lexical_results: list[RetrievedChunk],
    top_k: int,
    topic: str | None = None,
    customer_product_weights: dict[str, float] | None = None,
) -> list[RetrievedChunk]:
    """Fuse independently ranked dense/BM25 lists, then rerank their union with PPR."""
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
            existing = merged.get(item.chunk_id)
            if existing is None:
                merged[item.chunk_id] = (item, score)
                continue
            current_item, current_score = existing
            current_item.similarity = max(current_item.similarity, item.similarity)
            if item.ranking_score is not None:
                current_item.ranking_score = item.ranking_score
            merged[item.chunk_id] = (current_item, current_score + score)

    for chunk_id, (item, score) in list(merged.items()):
        if topic_matches(item.metadata, topic):
            score += topic_step
        if topic == "products" and _is_catalog_product_chunk(item):
            score += 2 * topic_step
        merged[chunk_id] = (item, score)

    ranked = sorted(merged.values(), key=lambda pair: (-pair[1], pair[0].chunk_id))
    reranked = _personalized_pagerank_rerank(
        [item for item, _score in ranked],
        [score for _item, score in ranked],
        customer_product_weights,
    )
    return _diverse_candidates(
        reranked, top_k,
        max_per_document=4 if topic == "products" else 2,
    )


def _retrieve_lexical(
    query: str,
    db: Session,
    top_k: int,
    business_id: int,
    query_topic: str | None = None,
    similarity_threshold: float | None = None,
) -> list[RetrievedChunk]:
    """Generate tenant-scoped lexical candidates and rank them with BM25."""
    sku_codes = identifiers(query)
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
    dialect = getattr(getattr(db, "bind", None), "dialect", None)
    if getattr(dialect, "name", "") == "sqlite":
        # SQLite QA uses the same folding function as production ranking.
        db.connection().connection.driver_connection.create_function("rag_fold", 1, fold_topic_text)
        searchable = (
            "COALESCE(CAST(dc.content AS TEXT), '') || ' ' "
            "|| COALESCE(json_extract(dc.metadata, '$.section'), '') || ' ' "
            "|| COALESCE(json_extract(dc.metadata, '$.context'), '')"
        )
        search_sql = f"rag_fold({searchable})"
    else:
        accents = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
        params["fold_from"] = accents
        params["fold_to"] = "".join(
            "d" if c == "đ" else "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
            for c in accents
        )
        searchable = (
            "COALESCE(CAST(dc.content AS TEXT), '') || ' ' "
            "|| COALESCE(dc.metadata ->> 'section', '') || ' ' "
            "|| COALESCE(dc.metadata ->> 'context', '')"
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
    all_conditions = sku_conditions + conditions
    match_count = " + ".join(f"CASE WHEN {condition} THEN 1 ELSE 0 END" for condition in conditions) or "0"
    sku_order = ("CASE WHEN (" + " OR ".join(sku_conditions) + ") THEN 0 ELSE 1 END, ") if sku_conditions else ""
    rows = db.execute(sa_text(f"""
        WITH scoped AS MATERIALIZED (
            SELECT dc.id, dc.document_id, dc.content, dc.metadata AS chunk_metadata,
                   d.filename AS source_filename, dc.chunk_index,
                   {normalized_column} AS search_text
            FROM document_chunks dc JOIN documents d ON d.id = dc.document_id
            WHERE d.status = 'ready' AND d.business_id = :business_id
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
        ))
        folded = fold_topic_text(searchable)
        matches = [any(contains(folded, alias) for alias in aliases) for aliases in terms]
        exact_sku = any(re.search(r"(?<![\w-])" + re.escape(sku) + r"(?![\w-])", data["content"].casefold()) for sku in sku_codes)
        if sku_codes and not exact_sku:
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
