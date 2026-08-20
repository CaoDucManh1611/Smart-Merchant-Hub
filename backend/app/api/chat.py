"""
Chat API – RAG-powered Q&A endpoint.

Hỗ trợ:
- POST /chat – non-streaming response
- POST /chat/stream – SSE streaming response
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.rag.retriever import retrieve
from app.rag.prompt_builder import build_prompt
from app.rag.llm_caller import call_llm, stream_llm
from app.rag.run_logger import RagRunLog
from app.schemas.rag import ChatRequest, ChatResponse, SourceChunk

logger = logging.getLogger(__name__)

router = APIRouter()


# =========================================================
# NON-STREAMING CHAT
# =========================================================


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
):
    """
    Gửi câu hỏi → RAG tìm context → LLM trả lời.

    Returns:
        Câu trả lời + danh sách sources tham khảo.
    """
    with RagRunLog(
        "chat",
        query_preview=request.query[:500],
        top_k=request.top_k,
    ) as run:
      try:
        # Bước 1: Retrieve relevant chunks
        run.update(phase="retrieve")
        chunks = retrieve(
            query=request.query,
            db=db,
            top_k=request.top_k,
        )

        run.update(
            phase="build_prompt",
            chunks_found=len(chunks),
            source_document_ids=sorted({c.document_id for c in chunks}),
            top_similarity=round(max((c.similarity for c in chunks), default=0), 4),
        )

        # Bước 2: Build prompt
        messages = build_prompt(
            query=request.query,
            chunks=chunks,
            conversation_history=request.conversation_history,
        )

        # Bước 3: Call LLM
        run.update(phase="llm")
        answer = call_llm(messages)
        run.finish(
            "no_context" if not chunks else "success",
            phase="complete",
            answer_chars=len(answer or ""),
        )

        # Bước 4: Build response
        sources = [
            SourceChunk(
                document_id=c.document_id,
                content=c.content[:200] + "..."
                if len(c.content) > 200
                else c.content,
                similarity=round(c.similarity, 4),
                metadata=c.metadata,
            )
            for c in chunks
        ]

        return ChatResponse(
            answer=answer,
            sources=sources,
            chunks_found=len(chunks),
        )

      except Exception as e:
          logger.exception("Chat error: %s", str(e))
          raise HTTPException(
              500,
              f"Lỗi khi xử lý câu hỏi: {str(e)}",
          )


# =========================================================
# STREAMING CHAT (SSE)
# =========================================================


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    db: Session = Depends(get_db),
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
            query_preview=request.query[:500],
            top_k=request.top_k,
        ) as run:
          try:
            # Retrieve
            run.update(phase="retrieve")
            chunks = retrieve(
                query=request.query,
                db=db,
                top_k=request.top_k,
            )

            run.update(
                phase="build_prompt",
                chunks_found=len(chunks),
                source_document_ids=sorted({c.document_id for c in chunks}),
                top_similarity=round(max((c.similarity for c in chunks), default=0), 4),
            )

            # Build prompt
            messages = build_prompt(
                query=request.query,
                chunks=chunks,
                conversation_history=request.conversation_history,
            )

            # Gửi sources trước
            sources = [
                {
                    "document_id": c.document_id,
                    "content": c.content[:200] + "..."
                    if len(c.content) > 200
                    else c.content,
                    "similarity": round(c.similarity, 4),
                    "metadata": c.metadata,
                }
                for c in chunks
            ]
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources, 'chunks_found': len(chunks)}, ensure_ascii=False)}\n\n"

            # Stream LLM response
            run.update(phase="llm")
            answer_chars = 0
            async for text_chunk in stream_llm(messages):
                answer_chars += len(text_chunk)
                payload = json.dumps(
                    {"type": "chunk", "content": text_chunk},
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"

            run.finish(
                "no_context" if not chunks else "success",
                phase="complete",
                answer_chars=answer_chars,
            )

            # Done
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

          except Exception as e:
              logger.exception("Stream error: %s", str(e))
              run.finish(
                  "error",
                  phase="complete",
                  error_type=type(e).__name__,
                  error=str(e)[:1000],
              )
              error_payload = json.dumps(
                  {"type": "error", "message": str(e)},
                  ensure_ascii=False,
              )
              yield f"data: {error_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
