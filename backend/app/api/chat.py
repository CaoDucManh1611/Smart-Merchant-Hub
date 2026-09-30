"""
Chat API – RAG-powered Q&A endpoint.

Hỗ trợ:
- POST /chat – non-streaming response
- POST /chat/stream – SSE streaming response
"""

import json
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.tenancy.crm_session import get_tenant_db
from app.rag.retriever import retrieve
from app.rag.answer_guard import has_valid_citations
from app.rag.topics import infer_query_topic
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.rag.prompt_builder import (
    NO_CONTEXT_CHAT_FALLBACK,
    SERVICE_ERROR_CHAT_FALLBACK,
    build_prompt,
    localize_rag_fallback,
)
from app.rag.llm_caller import call_llm, stream_llm
from app.rag.run_logger import RagRunLog
from app.schemas.rag import ChatRequest, ChatResponse, SourceChunk
from app.services.quota_service import QuotaExceededError, reserve_ai_budget
from app.services.recommendation_interaction_service import (
    RecommendationInteractionError,
    record_interaction,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _record_customer_question(
    db: Session,
    *,
    business_id: int,
    request: ChatRequest,
    idempotency_key: str | None,
) -> None:
    """Persist customer RAG intent when the caller supplied a CRM customer."""
    if request.customer_id is None:
        return
    event_key = (idempotency_key or "").strip() or uuid4().hex
    try:
        record_interaction(
            db,
            business_id=business_id,
            customer_id=request.customer_id,
            product_id=None,
            request_id=None,
            event_type="ask",
            source="rag",
            # Store only a short fingerprint; the full text is already kept
            # with the conversation where staff have the appropriate access.
            query=None,
            idempotency_key=f"rag-question:{event_key}",
            metadata={"top_k": request.top_k, "query_chars": len(request.query)},
            occurred_at=None,
        )
        # Keep the behavioral event durable even if the model call later fails
        # or the tenant has exhausted its AI budget.
        db.commit()
    except RecommendationInteractionError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


# =========================================================
# NON-STREAMING CHAT
# =========================================================


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key", max_length=120),
):
    """
    Gửi câu hỏi → RAG tìm context → LLM trả lời.

    Returns:
        Câu trả lời + danh sách sources tham khảo.
    """
    with RagRunLog(
        "chat",
        business_id=tenant.business_id,
        query_preview=request.query[:500],
        top_k=request.top_k,
    ) as run:
      try:
        _record_customer_question(
            db,
            business_id=tenant.business_id,
            request=request,
            idempotency_key=idempotency_key,
        )
        # Bước 1: Retrieve relevant chunks
        run.update(phase="retrieve")
        retrieval_started = perf_counter()
        chunks = retrieve(
            query=request.query,
            db=db,
            business_id=tenant.business_id,
            top_k=request.top_k,
        )

        run.update(
            phase="build_prompt",
            chunks_found=len(chunks),
            source_document_ids=sorted({c.document_id for c in chunks}),
            top_similarity=round(max((c.similarity for c in chunks), default=0), 4),
            retrieval_topic=infer_query_topic(request.query),
            retrieval_ms=round((perf_counter() - retrieval_started) * 1000, 2),
        )

        if not chunks:
            fallback = localize_rag_fallback(
                NO_CONTEXT_CHAT_FALLBACK,
                query=request.query,
                conversation_history=request.conversation_history,
            )
            run.finish("no_context", phase="complete", answer_chars=len(fallback), handoff_required=True)
            return ChatResponse(
                answer=fallback,
                sources=[],
                chunks_found=0,
                answer_status="no_context",
                handoff_required=True,
            )

        # Bước 2: Build prompt
        messages = build_prompt(
            query=request.query,
            chunks=chunks,
            conversation_history=request.conversation_history,
        )

        # Bước 3: Call LLM
        run.update(phase="llm")
        try:
            budget = reserve_ai_budget(
                db,
                tenant.business_id,
                messages,
                idempotency_key=(idempotency_key or "").strip() or f"chat:{uuid4().hex}",
            )
            # Charge before the provider call so failures cannot bypass the
            # tenant budget.  The request key makes safe client retries free.
            db.commit()
            run.update(estimated_ai_cost=float(budget["cost"]))
        except QuotaExceededError as exc:
            db.rollback()
            run.finish("quota_exceeded", phase="complete", quota=exc.detail)
            raise HTTPException(status_code=429, detail=exc.detail) from exc
        try:
            answer = call_llm(messages)
            if not answer or not answer.strip():
                raise RuntimeError("empty_llm_answer")
        except Exception as exc:
            logger.warning("RAG answer generation unavailable: error_type=%s", type(exc).__name__)
            fallback = localize_rag_fallback(
                SERVICE_ERROR_CHAT_FALLBACK,
                query=request.query,
                conversation_history=request.conversation_history,
            )
            run.finish("service_error", phase="complete", error_type=type(exc).__name__, handoff_required=True)
            return ChatResponse(
                answer=fallback,
                sources=[],
                chunks_found=len(chunks),
                answer_status="service_error",
                handoff_required=True,
            )
        if not has_valid_citations(answer, [chunk.content for chunk in chunks]):
            run.finish("no_context", phase="complete", reason="missing_or_invalid_citation", handoff_required=True)
            return ChatResponse(
                answer=localize_rag_fallback(
                    NO_CONTEXT_CHAT_FALLBACK,
                    query=request.query,
                    conversation_history=request.conversation_history,
                ),
                sources=[],
                chunks_found=len(chunks),
                answer_status="no_context",
                handoff_required=True,
            )
        run.finish("success", phase="complete", answer_chars=len(answer))

        # Bước 4: Build response
        sources = [
            SourceChunk(
                document_id=c.document_id,
                content=c.content[:200] + "..."
                if len(c.content) > 200
                else c.content,
                similarity=round(c.similarity, 4),
                metadata=c.metadata,
                citation_id=index,
                chunk_id=c.chunk_id,
                filename=c.filename or (c.metadata or {}).get("source"),
                chunk_index=c.chunk_index,
            )
            for index, c in enumerate(chunks, start=1)
        ]

        return ChatResponse(
            answer=answer,
            sources=sources,
            chunks_found=len(chunks),
            answer_status="answered",
            handoff_required=False,
        )

      except HTTPException:
          raise
      except Exception as e:
          logger.error("Chat failed: error_type=%s", type(e).__name__)
          raise HTTPException(
              500,
              "Lỗi khi xử lý câu hỏi. Vui lòng thử lại sau.",
          )


# =========================================================
# STREAMING CHAT (SSE)
# =========================================================


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key", max_length=120),
):
    """
    Gửi câu hỏi → RAG → LLM streaming response qua SSE.

    Event format:
        data: {"type": "chunk", "content": "..."}
        data: {"type": "sources", "sources": [...]}
        data: {"type": "done"}
    """

    async def event_generator():
        with RagRunLog(
            "chat_stream",
            business_id=tenant.business_id,
            query_preview=request.query[:500],
            top_k=request.top_k,
        ) as run:
          try:
            _record_customer_question(
                db,
                business_id=tenant.business_id,
                request=request,
                idempotency_key=idempotency_key,
            )
            # Retrieve
            run.update(phase="retrieve")
            retrieval_started = perf_counter()
            chunks = retrieve(
                query=request.query,
                db=db,
                business_id=tenant.business_id,
                top_k=request.top_k,
            )

            run.update(
                phase="build_prompt",
                chunks_found=len(chunks),
                source_document_ids=sorted({c.document_id for c in chunks}),
                top_similarity=round(max((c.similarity for c in chunks), default=0), 4),
                retrieval_topic=infer_query_topic(request.query),
                retrieval_ms=round((perf_counter() - retrieval_started) * 1000, 2),
            )

            sources = [
                {
                    "document_id": c.document_id,
                    "content": c.content[:200] + "..." if len(c.content) > 200 else c.content,
                    "similarity": round(c.similarity, 4),
                    "metadata": c.metadata,
                    "citation_id": index,
                    "chunk_id": c.chunk_id,
                    "filename": c.filename or (c.metadata or {}).get("source"),
                    "chunk_index": c.chunk_index,
                }
                for index, c in enumerate(chunks, start=1)
            ]
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources, 'chunks_found': len(chunks)}, ensure_ascii=False)}\n\n"

            if not chunks:
                fallback = localize_rag_fallback(
                    NO_CONTEXT_CHAT_FALLBACK,
                    query=request.query,
                    conversation_history=request.conversation_history,
                )
                run.finish("no_context", phase="complete", answer_chars=len(fallback), handoff_required=True)
                yield f"data: {json.dumps({'type': 'chunk', 'content': fallback}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'answer_status': 'no_context', 'handoff_required': True})}\n\n"
                return

            # Build prompt
            messages = build_prompt(
                query=request.query,
                chunks=chunks,
                conversation_history=request.conversation_history,
            )

            try:
                budget = reserve_ai_budget(
                    db,
                    tenant.business_id,
                    messages,
                    idempotency_key=(idempotency_key or "").strip() or f"chat-stream:{uuid4().hex}",
                )
                db.commit()
                run.update(estimated_ai_cost=float(budget["cost"]))
            except QuotaExceededError as exc:
                db.rollback()
                run.finish("quota_exceeded", phase="complete", quota=exc.detail)
                error_payload = json.dumps(
                    {"type": "error", "code": "quota_exceeded", "detail": exc.detail},
                    ensure_ascii=False,
                )
                yield f"data: {error_payload}\n\n"
                return

            # Stream LLM response
            run.update(phase="llm")
            answer_parts = []
            async for text_chunk in stream_llm(messages):
                answer_parts.append(text_chunk)

            answer = "".join(answer_parts)
            if not has_valid_citations(answer, [chunk.content for chunk in chunks]):
                run.finish("no_context", phase="complete", reason="missing_or_invalid_citation", handoff_required=True)
                fallback = localize_rag_fallback(
                    NO_CONTEXT_CHAT_FALLBACK,
                    query=request.query,
                    conversation_history=request.conversation_history,
                )
                yield f"data: {json.dumps({'type': 'chunk', 'content': fallback}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'answer_status': 'no_context', 'handoff_required': True})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'chunk', 'content': answer}, ensure_ascii=False)}\n\n"

            run.finish(
                "success",
                phase="complete",
                answer_chars=len(answer),
            )

            # Done
            yield f"data: {json.dumps({'type': 'done', 'answer_status': 'answered', 'handoff_required': False})}\n\n"

          except Exception as e:
              logger.warning("RAG stream failed: error_type=%s", type(e).__name__)
              is_quota = isinstance(e, QuotaExceededError)
              run.finish(
                  "quota_exceeded" if is_quota else "service_error",
                  phase="complete",
                  error_type=type(e).__name__,
                  handoff_required=not is_quota,
              )
              if is_quota:
                  error_payload = {
                      "type": "error",
                      "code": "quota_exceeded",
                      "message": e.detail,
                      "answer_status": "service_error",
                      "handoff_required": False,
                  }
              else:
                  logger.warning("RAG stream failed: error_type=%s", type(e).__name__)
                  error_payload = {
                      "type": "error",
                      "code": "service_unavailable",
                      "content": SERVICE_ERROR_CHAT_FALLBACK,
                      "answer_status": "service_error",
                      "handoff_required": True,
                      "replace": True,
                  }
              yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
