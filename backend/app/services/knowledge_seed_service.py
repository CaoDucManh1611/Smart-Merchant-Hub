"""Tự động nạp knowledge base seed khi backend khởi động."""

import logging
from pathlib import Path

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.document import Document
from app.rag.loader import LOADERS, detect_file_type
from app.services.ingestion_service import ingest_document

logger = logging.getLogger(__name__)
SEED_DATASET_VERSION = "v3-100k-products-10k-faq-curated"


def seed_knowledge_base() -> None:
    """Nạp các file seed mới nếu chưa có hoặc file nguồn đã thay đổi."""
    logger.info("Starting automatic knowledge-base seed: %s", SEED_DATASET_VERSION)
    if not settings.RAG_AUTO_SEED_ENABLED:
        logger.info("Automatic knowledge-base seeding is disabled")
        return

    seed_dir = Path(settings.RAG_AUTO_SEED_DIR)
    if not seed_dir.exists():
        logger.warning("Knowledge-base seed directory not found: %s", seed_dir)
        return

    files = sorted(
        path
        for path in seed_dir.iterdir()
        if path.is_file() and detect_file_type(path.name) in LOADERS
    )
    if not files:
        logger.info("No supported files found for automatic knowledge-base seeding")
        return

    db = SessionLocal()
    try:
        for path in files:
            file_bytes = path.read_bytes()
            existing = (
                db.query(Document)
                .filter(Document.filename == path.name)
                .order_by(Document.uploaded_at.desc())
                .first()
            )

            if existing and existing.file_size == len(file_bytes) and existing.status == "ready":
                logger.info("Skipping unchanged seed file %s", path.name)
                continue

            if existing is None:
                existing = Document(
                    filename=path.name,
                    file_type=detect_file_type(path.name),
                    file_size=len(file_bytes),
                    status="pending",
                )
                db.add(existing)
                db.commit()
                db.refresh(existing)
            else:
                existing.file_size = len(file_bytes)
                existing.status = "pending"
                existing.error_message = None
                db.commit()

            logger.info("Auto-seeding knowledge-base file: %s", path.name)
            ingest_document(
                existing.id,
                file_bytes,
                path.name,
                db,
                use_embeddings=not settings.RAG_AUTO_SEED_FAST_MODE,
            )
    except Exception:
        logger.exception("Automatic knowledge-base seeding failed")
    finally:
        db.close()
