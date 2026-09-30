"""Explicit, per-tenant knowledge-base seeding.

Seeding is a provisioning operation, not an application-startup side effect.
That prevents one backend restart from writing the same dataset into every
active shop schema.
"""

import logging
from pathlib import Path

from app.core.config import settings
from sqlalchemy import select

from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.models.platform_control import TenantRegistry
from app.tenancy.schema import schema_name_for, validate_schema_name
from app.models.document import Document
from app.rag.loader import LOADERS, detect_file_type
from app.services.ingestion_service import ingest_document

logger = logging.getLogger(__name__)
SEED_DATASET_VERSION = "v3-100k-products-10k-faq-curated"


def _seed_for_tenant(db, *, business_id: int, files: list[Path]) -> None:
    for path in files:
        file_bytes = path.read_bytes()
        existing = (
            db.query(Document)
            .filter(Document.business_id == business_id, Document.filename == path.name)
            .order_by(Document.uploaded_at.desc())
            .first()
        )

        if existing and existing.file_size == len(file_bytes) and existing.status == "ready":
            logger.info("Skipping unchanged seed file %s for business=%s", path.name, business_id)
            continue

        if existing is None:
            existing = Document(
                business_id=business_id,
                filename=path.name,
                file_type=detect_file_type(path.name),
                file_size=len(file_bytes),
                status="pending",
                source_bytes=file_bytes,
            )
            db.add(existing)
            db.commit()
            db.refresh(existing)
        else:
            existing.file_size = len(file_bytes)
            existing.source_bytes = file_bytes
            existing.status = "pending"
            existing.error_message = None
            db.commit()

        logger.info("Auto-seeding knowledge-base file: business=%s file=%s", business_id, path.name)
        ingest_document(
            existing.id,
            file_bytes,
            path.name,
            db,
            use_embeddings=not settings.RAG_AUTO_SEED_FAST_MODE,
            business_id=business_id,
        )


def seed_knowledge_base(*, business_id: int | None = None) -> None:
    """Seed exactly one active shop schema.

    ``business_id=None`` is intentionally a no-op.  Callers must opt in to a
    concrete shop during provisioning or invoke the tenant seed CLI.
    """
    logger.info("Starting automatic knowledge-base seed: %s", SEED_DATASET_VERSION)
    if business_id is None:
        logger.warning("Refusing global knowledge-base seed; business_id is required")
        return
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

    try:
        with PlatformSessionLocal() as platform_db:
            query = select(TenantRegistry).where(
                TenantRegistry.state == "active",
                TenantRegistry.feature_enabled.is_(True),
            )
            query = query.where(TenantRegistry.business_id == int(business_id))
            registries = platform_db.scalars(query.order_by(TenantRegistry.business_id.asc())).all()
            for registry in registries:
                schema = validate_schema_name(registry.schema_name)
                if schema != schema_name_for(registry.business_id):
                    logger.warning("Skipping invalid tenant registry schema for business=%s", registry.business_id)
                    continue
                with tenant_session(schema) as db:
                    _seed_for_tenant(db, business_id=int(registry.business_id), files=files)
    except Exception:
        logger.exception("Automatic knowledge-base seeding failed")
