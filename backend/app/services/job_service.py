"""Small database-backed job dispatcher used by CRM subsystems."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crm_job import CrmJob


MAX_ERROR_LENGTH = 500


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
) -> int:
    now = _now()
    jobs = db.query(CrmJob).filter(
        CrmJob.business_id == business_id,
        CrmJob.status == "pending",
        CrmJob.run_at <= now,
    ).order_by(CrmJob.run_at.asc(), CrmJob.id.asc()).limit(limit).all()
    processed = 0
    for job in jobs:
        job.status = "running"
        job.locked_at = now
        job.attempts = int(job.attempts or 0) + 1
        db.flush()
        handler = handlers.get(job.kind)
        try:
            if handler is None:
                raise RuntimeError(f"No handler registered for {job.kind}")
            handler(job.payload or {})
        except Exception as exc:  # noqa: BLE001 - persist bounded retry state
            job.last_error = str(exc)[:MAX_ERROR_LENGTH]
            if job.attempts >= job.max_attempts:
                job.status = "failed"
            else:
                job.status = "pending"
                job.run_at = now + timedelta(seconds=min(300, 2 ** max(0, job.attempts - 1)))
            job.locked_at = None
        else:
            job.status = "succeeded"
            job.last_error = None
            job.locked_at = None
        processed += 1
        db.commit()
    return processed
