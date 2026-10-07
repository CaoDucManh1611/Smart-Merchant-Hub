"""Hybrid retriever backed by PostgreSQL + pgvector.

The retriever combines semantic search (pgvector) with a lightweight lexical
fallback.  This is useful for product names, SKUs and Vietnamese terms that
may not always be represented well by an embedding model.
"""

import logging
import re
import time
from dataclasses import dataclass, replace

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.embedder import embed_query
from app.rag.run_logger import query_metadata
from app.rag.topics import infer_query_topic, topic_matches

logger = logging.getLogger(__name__)

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


def retrieve(
    query: str,
    db: Session,
    business_id: int,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
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
        similarity_threshold=similarity_threshold,
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
        query_vector = embed_query(query)
    except Exception as error:
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
        return _expand_parent_neighbors(lexical_results[:top_k], db, business_id, top_k)

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
        ORDER BY dc.embedding <=> CAST(:query_vector AS vector)
        LIMIT :top_k
    """

    try:
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
        return _expand_parent_neighbors(lexical_results[:top_k], db, business_id, top_k)

    vector_results = []
    for row in rows:
        row_data = row._mapping
        vector_results.append(
            RetrievedChunk(
                chunk_id=row_data["id"],
                document_id=row_data["document_id"],
                content=row_data["content"],
                similarity=float(row_data["similarity"]),
                metadata=row_data["chunk_metadata"],
                filename=row_data["source_filename"],
                chunk_index=row_data["chunk_index"],
            )
        )

    results = _merge_hybrid_results(vector_results, lexical_results, top_k, topic=query_topic)

    logger.info(
        "Retrieved %d chunks (top_k=%d, threshold=%.2f, topic=%s, lexical=%d, vector=%d, duration_ms=%.2f)",
        len(results),
        top_k,
        similarity_threshold,
        query_topic,
        len(lexical_results),
        len(vector_results),
        (time.perf_counter() - started) * 1000,
    )

    return _expand_parent_neighbors(results, db, business_id, top_k)


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
                        and (data["chunk_metadata"] or {}).get("parent_id") == metadata["parent_id"]
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
        metadata = data["chunk_metadata"] or {}
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
) -> list[RetrievedChunk]:
    """Merge semantic and lexical candidates without duplicate chunks."""
    merged: dict[int, tuple[RetrievedChunk, float]] = {}

    for item in vector_results:
        # Semantic search is the primary signal.
        topic_bonus = 0.15 if topic_matches(item.metadata, topic) else 0
        merged[item.chunk_id] = (item, 0.65 * item.similarity + topic_bonus)

    for item in lexical_results:
        existing = merged.get(item.chunk_id)
        if existing is None:
            topic_bonus = 0.15 if topic_matches(item.metadata, topic) else 0
            merged[item.chunk_id] = (item, 0.35 * item.similarity + topic_bonus)
            continue

        current_item, current_score = existing
        current_item.similarity = max(current_item.similarity, item.similarity)
        merged[item.chunk_id] = (
            current_item,
            current_score + 0.35 * item.similarity + (0.15 if topic_matches(item.metadata, topic) else 0),
        )

    ranked = sorted(merged.values(), key=lambda pair: pair[1], reverse=True)
    return [item for item, _score in ranked[:top_k]]


def _retrieve_lexical(
    query: str,
    db: Session,
    top_k: int,
    business_id: int,
    query_topic: str | None = None,
    similarity_threshold: float | None = None,
) -> list[RetrievedChunk]:
    """Tìm kiếm từ khóa trong toàn bộ chunks, kể cả chunk không có vector."""
    identifiers = list(
        dict.fromkeys(
            match.lower()
            for match in re.findall(
                r"\b[A-Za-z]{2,10}-\d{3,}\b",
                query,
            )
        )
    )
    tokens = [
        token.lower()
        for token in re.findall(r"[\wÀ-ỹ]+", query, flags=re.UNICODE)
        if len(token) >= 2 and token.lower() not in _STOP_WORDS
    ]
    if not tokens and not identifiers:
        return []

    token_conditions = [
        f"LOWER(dc.content) LIKE :term_{index}"
        for index in range(len(tokens))
    ]
    identifier_conditions = [
        f"LOWER(dc.content) LIKE :identifier_{index}"
        for index in range(len(identifiers))
    ]
    conditions = " OR ".join(identifier_conditions + token_conditions)
    params = {
        f"term_{index}": f"%{token}%"
        for index, token in enumerate(tokens)
    }
    params.update(
        {
            f"identifier_{index}": f"%{identifier}%"
            for index, identifier in enumerate(identifiers)
        }
    )
    match_count_order = " + ".join(
        f"CASE WHEN {condition} THEN 1 ELSE 0 END"
        for condition in token_conditions
    ) or "0"
    order_parts = []
    if identifier_conditions:
        order_parts.append(
            "CASE WHEN (" + " OR ".join(identifier_conditions) + ") THEN 0 ELSE 1 END"
        )
    order_parts.extend((f"({match_count_order}) DESC", "dc.id"))
    candidate_order = ", ".join(order_parts)
    rows = db.execute(
        sa_text(
            f"""
            SELECT dc.id, dc.document_id, dc.content, dc.metadata AS chunk_metadata,
                   d.filename AS source_filename, dc.chunk_index
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE d.status = 'ready'
              AND d.business_id = :business_id
              AND ({conditions})
            ORDER BY {candidate_order}
            LIMIT :candidate_limit
            """
        ),
        {**params, "business_id": business_id, "candidate_limit": max(100, top_k * 40)},
    ).fetchall()

    scored: list[tuple[float, RetrievedChunk]] = []
    for row in rows:
        row_data = row._mapping
        content = row_data["content"]
        content_lower = content.lower()
        content_tokens = set(re.findall(r"[\wÀ-ỹ]+", content_lower, flags=re.UNICODE))
        matched = sum(token in content_tokens for token in tokens)
        coverage = matched / len(tokens) if tokens else 0
        exact_identifier = any(
            identifier in content_lower
            for identifier in identifiers
        )
        phrase_bonus = 0.12 if " ".join(tokens[:2]) in content_lower else 0
        identifier_bonus = 0.35 if exact_identifier else 0
        score = min(0.99, coverage * 0.7 + phrase_bonus + identifier_bonus)
        if similarity_threshold is not None and score < similarity_threshold:
            continue
        topic_bonus = 0.15 if topic_matches(row_data["chunk_metadata"], query_topic) else 0
        scored.append((score + topic_bonus, RetrievedChunk(
                chunk_id=row_data["id"],
                document_id=row_data["document_id"],
                content=content,
                similarity=score,
                metadata=row_data["chunk_metadata"],
                filename=row_data["source_filename"],
                chunk_index=row_data["chunk_index"],
            )))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _rank, item in scored[:top_k]]
