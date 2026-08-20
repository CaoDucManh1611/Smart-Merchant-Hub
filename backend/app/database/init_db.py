import logging

from sqlalchemy import text

from app.core.config import settings
from app.database.session import Base, engine
from app.models.customer import Customer
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.document import Document, DocumentChunk
from app.models.setting import AppSetting

logger = logging.getLogger(__name__)


def init_db() -> None:
    # Kích hoạt pgvector extension (cần chạy 1 lần)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(bind=engine)

    # create_all() does not add newly introduced columns to existing tables.
    # Keep this small compatibility migration idempotent for older databases.
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE customers "
                "ADD COLUMN IF NOT EXISTS avatar_url VARCHAR"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE messages "
                "ADD COLUMN IF NOT EXISTS direction VARCHAR(20) "
                "NOT NULL DEFAULT 'inbound'"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE messages "
                "ADD COLUMN IF NOT EXISTS media_type VARCHAR(30)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE messages "
                "ADD COLUMN IF NOT EXISTS media_url TEXT"
            )
        )

    # pgvector HNSW indexes support at most 2,000 dimensions for vector.
    # Gemini's 3,072-dimension embeddings still work, but use an exact scan
    # until the column/index is changed to a compatible representation.
    if settings.EMBEDDING_DIMENSION <= 2000:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw
                    ON document_chunks
                    USING hnsw (embedding vector_cosine_ops)
                    """
                )
            )
    else:
        logger.warning(
            "Skipping pgvector HNSW index: embedding dimension %d exceeds the 2,000-dimension limit",
            settings.EMBEDDING_DIMENSION,
        )

    logger.info("Database schema and pgvector index are ready")


if __name__ == "__main__":
    init_db()
