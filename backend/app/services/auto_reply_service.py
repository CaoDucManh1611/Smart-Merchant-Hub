"""
Auto Reply Service – Tự động trả lời tin nhắn từ RAG knowledge base khi có tin nhắn inbound.
"""

import json
import logging
from threading import Thread

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.setting import AppSetting

from app.rag.retriever import retrieve
from app.rag.prompt_builder import build_prompt
from app.rag.llm_caller import call_llm
from app.rag.run_logger import RagRunLog
from app.services.facebook_service import send_facebook_message
from app.services.instagram_service import send_instagram_message

logger = logging.getLogger(__name__)

AUTO_REPLY_SETTING_KEY = "rag_auto_reply_enabled"


def _get_conversation_recipient(
    db: Session,
    conversation_id: int,
) -> tuple[str, str]:
    """Return channel and platform recipient id for a conversation."""
    row = db.execute(
        text(
            """
            SELECT cv.channel, c.external_user_id
            FROM conversations cv
            JOIN customers c ON c.id = cv.customer_id
            WHERE cv.id = :conversation_id
            LIMIT 1
            """
        ),
        {"conversation_id": conversation_id},
    ).mappings().first()

    if row is None or not row["external_user_id"]:
        raise ValueError(
            f"Không tìm thấy recipient cho conversation {conversation_id}."
        )

    return row["channel"], str(row["external_user_id"])


def _save_auto_reply_outbound(
    db: Session,
    conversation_id: int,
    channel: str,
    recipient_id: str,
    external_message_id: str | None,
    content: str,
    meta_response: dict,
) -> None:
    """Persist the external reply so it appears in the CRM inbox."""
    db.execute(
        text(
            """
            INSERT INTO messages (
                conversation_id,
                channel,
                external_user_id,
                external_message_id,
                direction,
                content,
                raw_payload
            )
            VALUES (
                :conversation_id,
                :channel,
                :external_user_id,
                :external_message_id,
                'outbound',
                :content,
                CAST(:raw_payload AS JSONB)
            )
            ON CONFLICT (external_message_id) DO NOTHING
            """
        ),
        {
            "conversation_id": conversation_id,
            "channel": channel,
            "external_user_id": recipient_id,
            "external_message_id": external_message_id,
            "content": content,
            "raw_payload": json.dumps(meta_response, ensure_ascii=False, default=str),
        },
    )
    db.commit()


def get_auto_reply_enabled(db: Session) -> bool:
    setting = db.get(AppSetting, AUTO_REPLY_SETTING_KEY)
    return bool(setting and setting.value.lower() == "true")


def set_auto_reply_enabled(db: Session, enabled: bool) -> bool:
    value = "true" if enabled else "false"
    setting = db.get(AppSetting, AUTO_REPLY_SETTING_KEY)
    if setting is None:
        setting = AppSetting(key=AUTO_REPLY_SETTING_KEY, value=value)
        db.add(setting)
    else:
        setting.value = value
    db.commit()
    logger.info("RAG Auto-reply toggled to: %s", enabled)
    return enabled


def process_rag_auto_reply(
    db: Session,
    conversation_id: int,
    channel: str,
    query_text: str,
) -> bool:
    """
    Tự động tra cứu RAG và gửi tin nhắn phản hồi cho khách hàng.
    """
    with RagRunLog(
        "auto_reply",
        conversation_id=conversation_id,
        channel=channel,
        query_preview=(query_text or "")[:500],
        top_k=5,
    ) as run:
      if not get_auto_reply_enabled(db):
          run.finish("skipped", phase="complete", reason="auto_reply_disabled")
          return False

      if not query_text or not query_text.strip():
          run.finish("skipped", phase="complete", reason="empty_query")
          return False

      try:
        run.update(phase="retrieve")
        logger.info("Executing RAG auto-reply for conversation %d (query: %s)", conversation_id, query_text[:50])

        # 1. Retrieve
        chunks = retrieve(query=query_text, db=db, top_k=5)
        if not chunks:
            logger.info("No relevant RAG chunks found for query: %s", query_text[:50])
            run.finish("no_context", phase="complete", chunks_found=0)
            return False

        # 2. Build prompt
        run.update(
            phase="build_prompt",
            chunks_found=len(chunks),
            source_document_ids=sorted({c.document_id for c in chunks}),
            top_similarity=round(max((c.similarity for c in chunks), default=0), 4),
        )
        messages = build_prompt(query=query_text, chunks=chunks)

        # 3. Call LLM
        run.update(phase="llm")
        answer = call_llm(messages)
        if not answer or not answer.strip():
            logger.warning("Empty LLM answer for RAG auto-reply")
            run.finish("error", phase="complete", reason="empty_llm_answer", answer_chars=0)
            return False

        # 4. Resolve the platform recipient and send the reply.
        stored_channel, recipient_id = _get_conversation_recipient(
            db,
            conversation_id,
        )
        if stored_channel != channel:
            logger.warning(
                "Conversation channel mismatch: event=%s, database=%s",
                channel,
                stored_channel,
            )
            channel = stored_channel

        if channel == "facebook":
            meta_response = send_facebook_message(
                recipient_id=recipient_id,
                text=answer,
            )
            logger.info("RAG auto-reply sent via Facebook to conversation %d", conversation_id)
        elif channel == "instagram":
            meta_response = send_instagram_message(
                recipient_id=recipient_id,
                text=answer,
            )
            logger.info("RAG auto-reply sent via Instagram to conversation %d", conversation_id)
        else:
            run.finish("error", phase="complete", reason="unsupported_channel")
            return False

        _save_auto_reply_outbound(
            db=db,
            conversation_id=conversation_id,
            channel=channel,
            recipient_id=recipient_id,
            external_message_id=meta_response.get("message_id"),
            content=answer,
            meta_response=meta_response,
        )
        run.finish("success", phase="complete", answer_chars=len(answer))
        return True

      except Exception as e:
          logger.exception("RAG auto-reply error: %s", str(e))
          run.finish(
              "error",
              phase="complete",
              error_type=type(e).__name__,
              error=str(e)[:1000],
          )
          return False

    return False


def process_rag_auto_reply_background(
    conversation_id: int,
    channel: str,
    query_text: str,
) -> None:
    """Run RAG auto-reply off the webhook request path."""

    def worker() -> None:
        db = SessionLocal()
        try:
            process_rag_auto_reply(
                db=db,
                conversation_id=conversation_id,
                channel=channel,
                query_text=query_text,
            )
        finally:
            db.close()

    Thread(target=worker, daemon=True).start()
