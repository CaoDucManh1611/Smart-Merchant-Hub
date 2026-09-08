import logging
import time

from sqlalchemy import text

from app.core.config import settings
from app.database.bootstrap import ensure_default_business
from app.database.session import Base, SessionLocal, engine
from app.models.customer import Customer
from app.models.customer_merge import CustomerMerge
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.notification import Notification
from app.models.experimentation import RuleSuggestion, FeatureSnapshot, Experiment, ExperimentAssignment, ExperimentOutcome, BanditDecision
from app.models.customer_fact import CustomerFact
from app.models.business_setting import BusinessSetting
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.message_attachment import MessageAttachment
from app.models.document import Document, DocumentChunk
from app.models.setting import AppSetting
# Import all target models before create_all() so SQLAlchemy registers the
# full multi-tenant schema in one metadata graph.
from app.models.business import Business, Payment, ServicePlan, Subscription, User
from app.models.channel import Channel, ChannelEvent
from app.models.crm_extended import ConversationAssignment, ConversationTag, Tag
from app.models.ticket import TicketEvent
from app.models.sales import Order, OrderItem, Product
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.chatbot import ChatbotConfig
from app.models.canned_response import CannedResponse
from app.models.chatbot_followup import ChatbotFollowUp

logger = logging.getLogger(__name__)


def _wait_for_database(max_attempts: int = 15, delay_seconds: int = 2) -> None:
    """Wait briefly for PostgreSQL to accept connections during startup."""
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            logger.warning(
                "Database is not ready yet (%d/%d); retrying in %ds",
                attempt,
                max_attempts,
                delay_seconds,
            )
            time.sleep(delay_seconds)

    raise RuntimeError(
        "Khong ket noi duoc PostgreSQL. Hay kiem tra Docker Desktop, "
        "DATABASE_URL va cong 5432."
    ) from last_error


def init_db() -> None:
    _wait_for_database()

    # Kích hoạt pgvector extension (cần chạy 1 lần)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(bind=engine)

    # create_all() does not add newly introduced columns to existing tables.
    # Keep this small compatibility migration idempotent for older databases.
    with engine.begin() as conn:
        # The original project was a single-shop prototype. These nullable
        # columns allow old rows and environment-based credentials to keep
        # working while new tenants can use the normalized relations.
        conn.execute(
            text(
                "ALTER TABLE customers "
                "ADD COLUMN IF NOT EXISTS business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE customers "
                "ADD COLUMN IF NOT EXISTS email VARCHAR(255)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE customers "
                "ADD COLUMN IF NOT EXISTS phone VARCHAR(40)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE customers "
                "ADD COLUMN IF NOT EXISTS address TEXT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE customers "
                "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE customers "
                "DROP CONSTRAINT IF EXISTS uq_customers_channel_user"
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'uq_customers_business_channel_user'
                    ) THEN
                        ALTER TABLE customers
                        ADD CONSTRAINT uq_customers_business_channel_user
                        UNIQUE (business_id, channel, external_user_id);
                    END IF;
                END $$;
                """
            )
        )
        conn.execute(
            text(
                "ALTER TABLE conversations "
                "ADD COLUMN IF NOT EXISTS business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE conversations "
                "ADD COLUMN IF NOT EXISTS channel_id INTEGER REFERENCES channels(id) ON DELETE SET NULL"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE conversations "
                "ADD COLUMN IF NOT EXISTS priority VARCHAR(20) NOT NULL DEFAULT 'normal'"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE conversations "
                "ADD COLUMN IF NOT EXISTS assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE conversations "
                "ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMP"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE conversations "
                "ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE conversations "
                "ADD COLUMN IF NOT EXISTS bot_mode VARCHAR(20) NOT NULL DEFAULT 'auto'"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE chatbot_configs "
                "ADD COLUMN IF NOT EXISTS business_hours JSON"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE messages "
                "ADD COLUMN IF NOT EXISTS sender_type VARCHAR(20) NOT NULL DEFAULT 'customer'"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE messages "
                "ADD COLUMN IF NOT EXISTS sender_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE messages "
                "ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'received'"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE messages "
                "ADD COLUMN IF NOT EXISTS metadata JSON"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE messages "
                "ADD COLUMN IF NOT EXISTS sent_at TIMESTAMP"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE customers "
                "ADD COLUMN IF NOT EXISTS avatar_url VARCHAR"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE customers "
                "ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE customers "
                "ADD COLUMN IF NOT EXISTS merged_into_customer_id INTEGER "
                "REFERENCES customers(id) ON DELETE SET NULL"
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

    # Keep the built-in tenant available for the initial single-business
    # deployment. The Alembic seed migration performs the same operation for
    # fresh environments; this call also makes legacy create_all databases
    # safe to upgrade without a manual data step.
    with SessionLocal() as db:
        ensure_default_business(db)

    logger.info("Database schema and pgvector index are ready")


if __name__ == "__main__":
    init_db()
