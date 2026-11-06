"""Reconcile cross-database RAG chunk quota after an interrupted reindex.

Stop all RAG workers and writes first. Default is read-only. --repair requires
an explicit workers-stopped assertion and changes only the current-period
platform rag_chunks usage to the count of committed tenant chunks. Re-run is
idempotent. This does NOT restore a previously published index version.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, text

from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.models.crm_job import CrmJob
from app.models.document import Document, DocumentChunk
from app.models.platform_control import PlatformUsage, TenantRegistry
from app.models.rag_run import RagRun
from app.services.quota_service import quota_period_start
from app.tenancy.schema import schema_name_for, validate_schema_name


def reconcile_values(actual: int, reported: int | None, used: Decimal | None) -> dict:
    if actual < 0 or reported is not None and reported < 0:
        raise ValueError("negative chunk count")
    return {"actual_chunks": actual, "reported_chunks": reported,
            "platform_used": str(used) if used is not None else None,
            "quota_delta": str(Decimal(actual) - (used or Decimal(0))),
            "document_count_mismatch": reported is not None and actual != reported}


def run(business_id: int, *, repair: bool = False, workers_stopped: bool = False,
        abandon_stale: bool = False) -> dict:
    if business_id <= 0 or repair and not workers_stopped:
        raise ValueError("repair requires a positive tenant and --workers-stopped")
    if abandon_stale and not repair:
        raise ValueError("--abandon-stale requires --repair")
    with PlatformSessionLocal() as platform_db:
        registry = platform_db.scalar(select(TenantRegistry).where(
            TenantRegistry.business_id == business_id, TenantRegistry.state == "active"))
        if registry is None or validate_schema_name(registry.schema_name) != schema_name_for(business_id):
            raise ValueError("invalid tenant registry")
        with tenant_session(registry.schema_name) as db:
            if not repair and db.bind.dialect.name == "postgresql":
                db.execute(text("SET TRANSACTION READ ONLY"))
            active_runs = db.scalars(select(RagRun).where(
                RagRun.business_id == business_id,
                RagRun.status.in_(("queued", "processing")))).all()
            active_jobs = db.scalars(select(CrmJob).where(
                CrmJob.business_id == business_id, CrmJob.kind == "rag.ingest",
                CrmJob.status.in_(("pending", "running")))).all()
            if repair and (active_runs or active_jobs):
                if not abandon_stale:
                    raise ValueError("active RAG work exists; use --abandon-stale after stopping workers")
                cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30)
                if any((item.updated_at or item.created_at) > cutoff for item in [*active_runs, *active_jobs]):
                    raise ValueError("recent RAG work exists; refuse to abandon")
                for item in active_runs:
                    item.status = "failed"
                    item.phase = "complete"
                    item.error_code = "interrupted_reindex_reconciled"
                    item.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                for item in active_jobs:
                    item.status = "failed"
                    item.last_error = "interrupted_reindex_reconciled"
            rows = db.execute(select(
                Document.id, Document.chunk_count, func.count(DocumentChunk.id),
            ).outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id).where(
                Document.business_id == business_id).group_by(Document.id)).all()
            discrepancies = [reconcile_values(int(count), int(reported or 0), None) | {"document_id": int(doc_id)}
                             for doc_id, reported, count in rows if int(count) != int(reported or 0)]
            actual = sum(int(count) for _, _, count in rows)
            if repair and discrepancies:
                raise ValueError("document counts disagree with committed chunks; repair tenant metadata first")
            if repair and abandon_stale:
                # The tenant session must own this commit.  Committing after
                # leaving tenant_session() used a closed session and made the
                # recovery path fail exactly when stale jobs had to be marked.
                db.commit()
        period = quota_period_start()
        usage = platform_db.scalar(select(PlatformUsage).where(
            PlatformUsage.business_id == business_id,
            PlatformUsage.resource == "rag_chunks",
            PlatformUsage.period_start == period,
        ).with_for_update() if repair else select(PlatformUsage).where(
            PlatformUsage.business_id == business_id,
            PlatformUsage.resource == "rag_chunks",
            PlatformUsage.period_start == period))
        result = reconcile_values(actual, None, usage.used if usage else None)
        result.update({"business_id": business_id, "period_start": period.isoformat(),
                       "active_run": bool(active_runs), "active_job": bool(active_jobs),
                       "document_discrepancies": discrepancies, "repaired": False})
        if repair:
            if usage is None:
                usage = PlatformUsage(business_id=business_id, resource="rag_chunks",
                                      period_start=period, used=Decimal(actual))
                platform_db.add(usage)
            else:
                usage.used = Decimal(actual)
            platform_db.commit()
            result["repaired"] = True
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--business-id", type=int, required=True)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--workers-stopped", action="store_true")
    parser.add_argument("--abandon-stale", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.business_id, repair=args.repair,
                             workers_stopped=args.workers_stopped,
                             abandon_stale=args.abandon_stale), ensure_ascii=False))
    except Exception as error:
        parser.exit(2, json.dumps({"error_type": type(error).__name__, "repaired": False}) + "\n")


if __name__ == "__main__":
    main()
