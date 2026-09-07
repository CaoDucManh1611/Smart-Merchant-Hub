"""Small database-backed job dispatcher used by CRM subsystems."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections.abc import Collection
from typing import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crm_job import CrmJob


MAX_ERROR_LENGTH = 500
STALE_LOCK_AFTER = timedelta(minutes=5)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enqueue_job(
    db: Session,
    *,
    business_id: int,
    kind: str,
    payload: dict,
    idempotency_key: str,
    run_at: datetime | None = None,
    max_attempts: int = 5,
) -> CrmJob:
    existing = db.query(CrmJob).filter(CrmJob.business_id == business_id, CrmJob.idempotency_key == idempotency_key).first()
    if existing is not None:
        return existing
    row = CrmJob(
        business_id=business_id,
        kind=kind,
        payload=payload or {},
        status="pending",
        attempts=0,
        max_attempts=max(1, min(max_attempts, 10)),
        run_at=run_at or _now(),
        idempotency_key=idempotency_key,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(CrmJob).filter(CrmJob.business_id == business_id, CrmJob.idempotency_key == idempotency_key).first()
        if existing is None:
            raise
        return existing
    return row


def dispatch_due_jobs(
    db: Session,
    *,
    business_id: int,
    handlers: dict[str, Callable[[dict], object]],
    limit: int = 100,
    kinds: Collection[str] | None = None,
) -> int:
    now = _now()
    supported_kinds: set[str] | None = None
    if kinds is not None:
        supported_kinds = {str(kind) for kind in kinds if str(kind)}
        if not supported_kinds:
            return 0

    # A process can die after claiming a job.  Make that job eligible again
    # after a bounded lock period instead of leaving a CRM action stranded.
    stale_query = db.query(CrmJob).filter(
        CrmJob.business_id == business_id,
        CrmJob.status == "running",
        CrmJob.locked_at.is_not(None),
        CrmJob.locked_at <= now - STALE_LOCK_AFTER,
    )
    if supported_kinds is not None:
        stale_query = stale_query.filter(CrmJob.kind.in_(supported_kinds))
    stale_query.update(
        {CrmJob.status: "pending", CrmJob.locked_at: None, CrmJob.run_at: now},
        synchronize_session=False,
    )
    db.commit()

    processed = 0
    while processed < limit:
        query = db.query(CrmJob).filter(
            CrmJob.business_id == business_id,
            CrmJob.status == "pending",
            CrmJob.run_at <= now,
        )
        if supported_kinds is not None:
            query = query.filter(CrmJob.kind.in_(supported_kinds))
        # On PostgreSQL this prevents two worker processes from claiming the
        # same row.  SQLite (used by unit tests) safely ignores FOR UPDATE.
        job = query.order_by(CrmJob.run_at.asc(), CrmJob.id.asc()).with_for_update(skip_locked=True).first()
        if job is None:
            break
        job.status = "running"
        job.locked_at = now
        job.attempts = int(job.attempts or 0) + 1
        job_id = job.id
        # Persist the claim before invoking a handler.  Handlers such as the
        # workflow engine own their own transactions, so their commit/rollback
        # must never erase this job's retry state.
        db.commit()
        handler = handlers.get(job.kind)
        try:
            if handler is None:
                raise RuntimeError(f"No handler registered for {job.kind}")
            handler(job.payload or {})
        except Exception as exc:  # noqa: BLE001 - persist bounded retry state
            db.rollback()
            job = db.get(CrmJob, job_id)
            if job is None:
                processed += 1
                continue
            job.last_error = str(exc)[:MAX_ERROR_LENGTH]
            if job.attempts >= job.max_attempts:
                job.status = "failed"
            else:
                job.status = "pending"
                job.run_at = now + timedelta(seconds=min(300, 2 ** max(0, job.attempts - 1)))
            job.locked_at = None
        else:
            # Reload after a handler-owned commit so we update the durable row
            # rather than a stale ORM object.
            job = db.get(CrmJob, job_id)
            if job is None:
                processed += 1
                continue
            job.status = "succeeded"
            job.last_error = None
            job.locked_at = None
        processed += 1
        db.commit()
    return processed
