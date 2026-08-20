"""Hybrid retriever backed by PostgreSQL + pgvector.

The retriever combines semantic search (pgvector) with a lightweight lexical
fallback.  This is useful for product names, SKUs and Vietnamese terms that
may not always be represented well by an embedding model.
"""

import logging
import re
from dataclasses import dataclass

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.embedder import embed_query

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


def retrieve(
    query: str,
    db: Session,
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

    # Always collect lexical candidates.  They are especially important for
    # product names, SKU codes and documents ingested without embeddings.
    lexical_results = _retrieve_lexical(query, db, max(top_k * 3, top_k))
    vector_results: list[RetrievedChunk] = []

    # Bước 1: Embed câu hỏi thành vector; nếu hết quota vẫn dùng từ khóa.
    logger.info("Embedding query: %s", query[:100])
    try:
        query_vector = embed_query(query)
    except Exception as error:
        logger.warning("Vector query unavailable; using lexical retrieval: %s", error)
        return lexical_results[:top_k]

    # Search pgvector using a bound parameter.  Do not interpolate the vector
    # into SQL even though it currently comes from a trusted provider.
    vector_str = "[" + ",".join(f"{float(value):.10g}" for value in query_vector) + "]"
    raw_sql = """
        SELECT
            dc.id,
            dc.document_id,
            dc.content,
            dc.metadata AS chunk_metadata,
            1 - (dc.embedding <=> CAST(:query_vector AS vector)) AS similarity
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE d.status = 'ready'
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
                "threshold": similarity_threshold,
                "top_k": max(top_k * 3, top_k),
            },
        ).fetchall()
    except Exception as error:
        logger.warning(
            "pgvector search unavailable; using lexical retrieval: %s",
            error,
        )
        return lexical_results[:top_k]

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
            )
        )

    results = _merge_hybrid_results(vector_results, lexical_results, top_k)

    logger.info(
        "Retrieved %d chunks (top_k=%d, threshold=%.2f)",
        len(results),
        top_k,
        similarity_threshold,
    )

    return results


def _merge_hybrid_results(
    vector_results: list[RetrievedChunk],
    lexical_results: list[RetrievedChunk],
    top_k: int,
) -> list[RetrievedChunk]:
    """Merge semantic and lexical candidates without duplicate chunks."""
    merged: dict[int, tuple[RetrievedChunk, float]] = {}

    for item in vector_results:
        # Semantic search is the primary signal.
        merged[item.chunk_id] = (item, 0.65 * item.similarity)

    for item in lexical_results:
        existing = merged.get(item.chunk_id)
        if existing is None:
            merged[item.chunk_id] = (item, 0.35 * item.similarity)
            continue

        current_item, current_score = existing
        current_item.similarity = max(current_item.similarity, item.similarity)
        merged[item.chunk_id] = (
            current_item,
            current_score + 0.35 * item.similarity,
        )

    ranked = sorted(merged.values(), key=lambda pair: pair[1], reverse=True)
    return [item for item, _score in ranked[:top_k]]


def _retrieve_lexical(
    query: str,
    db: Session,
    top_k: int,
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
    exact_order = (
        "CASE WHEN ("
        + " OR ".join(identifier_conditions)
        + ") THEN 0 ELSE 1 END, dc.id"
        if identifier_conditions
        else "dc.id"
    )
    rows = db.execute(
        sa_text(
            f"""
            SELECT dc.id, dc.document_id, dc.content, dc.metadata AS chunk_metadata
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE d.status = 'ready' AND ({conditions})
            ORDER BY {exact_order}
            LIMIT :candidate_limit
            """
        ),
        {**params, "candidate_limit": max(100, top_k * 40)},
    ).fetchall()

    scored = []
    for row in rows:
        row_data = row._mapping
        content = row_data["content"]
        content_lower = content.lower()
        matched = sum(token in content_lower for token in tokens)
        coverage = matched / len(tokens) if tokens else 0
        exact_identifier = any(
            identifier in content_lower
            for identifier in identifiers
        )
        phrase_bonus = 0.12 if " ".join(tokens[:2]) in content_lower else 0
        identifier_bonus = 0.35 if exact_identifier else 0
        score = min(
            0.99,
            0.45 + coverage * 0.25 + phrase_bonus + identifier_bonus,
        )
        scored.append(
            RetrievedChunk(
                chunk_id=row_data["id"],
                document_id=row_data["document_id"],
                content=content,
                similarity=score,
                metadata=row_data["chunk_metadata"],
            )
        )

    scored.sort(key=lambda item: item.similarity, reverse=True)
    return scored[:top_k]
