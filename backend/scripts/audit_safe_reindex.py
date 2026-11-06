"""Read-only reindex plan for explicitly selected tenant/document IDs.

No apply mode, queue dispatch, quota reservation or remote model calls.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text

from app.core.config import settings
from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.models.crm_job import CrmJob
from app.models.document import Document, DocumentChunk
from app.models.platform_control import TenantRegistry
from app.models.rag_run import RagRun
from app.models.recommendation_catalog import RecommendationCatalogChunkMapping, RecommendationCatalogEntry
from app.models.sales import Product
from app.rag.loader import load_document
from app.rag.semantic_chunker import _SKU, chunk_document, contextual_embedding_text
from app.rag.topics import infer_document_topic
from app.tenancy.schema import schema_name_for, validate_schema_name


def _positive_id(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("IDs must be positive")
    return number


def audit_documents(db, *, business_id: int, document_ids: list[int]) -> dict:
    """Inspect only the selected tenant/documents; never mutate the session."""
    if business_id <= 0 or not document_ids or any(value <= 0 for value in document_ids):
        raise ValueError("Explicit positive business_id and document_ids are required")
    ids = sorted(set(document_ids))
    docs = db.scalars(select(Document).where(
        Document.business_id == business_id, Document.id.in_(ids),
    ).order_by(Document.id)).all()
    if {doc.id for doc in docs} != set(ids):
        raise ValueError("Selected documents do not all belong to this tenant")
    products = db.scalars(select(Product).where(Product.business_id == business_id)).all()
    patterns = {
        str(product.sku).strip().casefold(): re.compile(
            rf"(?<![\w-]){re.escape(str(product.sku).strip())}(?![\w-])", re.IGNORECASE,
        ) for product in products if str(product.sku or "").strip()
    }
    mapped = defaultdict(set)
    for chunk_id, sku in db.execute(
        select(RecommendationCatalogChunkMapping.document_chunk_id, RecommendationCatalogEntry.sku_norm)
        .join(RecommendationCatalogEntry)
        .join(DocumentChunk, DocumentChunk.id == RecommendationCatalogChunkMapping.document_chunk_id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.business_id == business_id, Document.id.in_(ids),
               RecommendationCatalogEntry.business_id == business_id)
    ):
        if sku:
            mapped[chunk_id].add(sku.casefold())

    def skus(content: str) -> set[str]:
        return ({sku for sku, pattern in patterns.items() if pattern.search(content)}
                | {sku.casefold() for sku in _SKU.findall(content)})

    results = []
    for doc in docs:
        chunks = db.scalars(select(DocumentChunk).where(
            DocumentChunk.document_id == doc.id,
        ).order_by(DocumentChunk.chunk_index)).all()
        mixed = []
        for chunk in chunks:
            content_skus = skus(chunk.content or "")
            mapped_skus = mapped[chunk.id]
            if len(content_skus | mapped_skus) > 1:
                mixed.append({"chunk_id": chunk.id, "chunk_index": chunk.chunk_index,
                              "content_skus": sorted(content_skus), "mapped_skus": sorted(mapped_skus)})
        active = db.scalar(select(RagRun.id).where(
            RagRun.business_id == business_id, RagRun.document_id == doc.id,
            RagRun.status.in_(("queued", "processing")),
        )) is not None
        active = active or db.scalar(select(CrmJob.id).where(
            CrmJob.business_id == business_id, CrmJob.kind == "rag.ingest",
            CrmJob.status.in_(("pending", "running")),
            CrmJob.payload["document_id"].as_integer() == doc.id,
        )) is not None
        result = {"document_id": doc.id, "filename": doc.filename, "status": doc.status,
                  "embedding_status": doc.embedding_status, "stored_chunks": len(chunks),
                  "reported_chunk_count": doc.chunk_count, "multi_sku_chunks": mixed,
                  "multi_sku_chunk_count": len(mixed), "active_run": active,
                  "has_source": bool(doc.source_bytes)}
        if doc.source_bytes:
            source = bytes(doc.source_bytes)
            try:
                raw = load_document(source, doc.filename)
                topic = infer_document_topic(doc.filename, raw)
                proposed = chunk_document(raw, doc.filename, chunk_size=settings.RAG_CHUNK_SIZE,
                                          semantic_boundary_detector=None)
                chars = sum(len(contextual_embedding_text(chunk)) for chunk in proposed)
                result.update(
                    source_sha256=hashlib.sha256(source).hexdigest(), topic=topic,
                    document_class="catalog" if topic == "products" else "policy" if topic in {
                        "delivery", "returns", "payments", "shop",
                    } else "guide_or_faq",
                    proposed_local_chunks=len(proposed),
                    additional_chunk_quota=max(0, len(proposed) - len(chunks)),
                    proposed_multi_sku_chunks=sum(len(skus(chunk.content)) > 1 for chunk in proposed),
                    embedding_input_chars=chars, estimated_embedding_tokens=(chars + 3) // 4,
                    estimated_embedding_cost=None,
                    eligible=bool(proposed) and not active and doc.status not in {"disabled", "superseded"},
                )
            except Exception as error:
                result.update(eligible=False, error_type=type(error).__name__)
        else:
            result["eligible"] = False
        results.append(result)
    return {"mode": "dry_run", "business_id": business_id, "selected_document_ids": ids,
            "documents": results, "network_model_calls": 0, "writes": 0,
            "notes": ["SKU inventory uses tenant catalog SKUs, explicit SKU labels and mappings; unlabelled unknown codes may be missed.",
                      "Mixed-SKU evidence is a review candidate, not an automatic corruption verdict.",
                      "Chunk/token counts use local boundaries; remote semantic boundaries may differ.",
                      "Tokens are a chars/4 estimate; cost is unknown. No quota is reserved.",
                      "Future execution must use the authenticated document reindex API and existing worker."]}


def run(*, business_id: int, document_ids: list[int]) -> dict:
    # Registry and tenant transactions are read-only even on a writable DSN.
    with PlatformSessionLocal() as platform_db:
        if platform_db.bind.dialect.name == "postgresql":
            platform_db.execute(text("SET TRANSACTION READ ONLY"))
        registry = platform_db.scalar(select(TenantRegistry).where(
            TenantRegistry.business_id == business_id,
            TenantRegistry.state == "active", TenantRegistry.feature_enabled.is_(True),
        ))
        if registry is None:
            raise ValueError("An active, enabled tenant registry entry is required")
        schema = validate_schema_name(registry.schema_name)
        if schema != schema_name_for(business_id):
            raise ValueError("Tenant registry schema mismatch")
    with tenant_session(schema) as db:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        return audit_documents(db, business_id=business_id, document_ids=document_ids)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--business-id", type=_positive_id, required=True)
    parser.add_argument("--document-id", type=_positive_id, action="append", required=True)
    parser.add_argument("--dry-run", action="store_true", help="read-only is the only supported mode")
    args = parser.parse_args()
    try:
        report = run(business_id=args.business_id, document_ids=args.document_id)
    except Exception as error:
        # Do not print DSNs or source contents on a failed audit.
        print(json.dumps({"mode": "dry_run", "error_type": type(error).__name__}))
        raise SystemExit(1) from None
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
