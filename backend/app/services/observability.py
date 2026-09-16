"""Safe operational health, metrics and alert snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.platform_control import PlatformUsage, TenantMigrationOperation, TenantRegistry
from app.models.crm_job import CrmJob
from app.models.saas import SaaSUsage
from app.services.channel_retry import provider_breaker_snapshot
from app.services.quota_service import quota_period_start


def collect_operational_snapshot(db: Session) -> dict:
    """Collect counters only; never include message bodies, URLs or secrets."""
    tenant_bound = bool(getattr(db, "info", {}).get("tenant_schema"))
    snapshot = {
        "database": {"status": "ok"},
        "platform_database": {"status": "unknown"},
        "tenant_database": {"status": "unknown"},
        "tenant_migrations": {
            "status": "unknown",
            "active": None,
            "migrating": None,
            "failed": None,
            "operations_pending": None,
        },
        "queue": {"status": "unknown", "pending": None, "running": None, "failed": None},
        "provider": {"status": "ok", "circuits": provider_breaker_snapshot()},
        "rate_limit": {"backend": settings.RATE_LIMIT_BACKEND, "status": "disabled" if not settings.RATE_LIMIT_ENABLED else "ok"},
        "ai": {"status": "ok", "cost": 0.0, "period_start": quota_period_start().isoformat()},
    }
    try:
        db.execute(text("SELECT 1"))
        # Queue rows live in each tenant schema.  A platform-only health
        # probe must not query a shared/legacy jobs table (which could leak
        # or accidentally mix shops), so it reports queue counters only when
        # the caller explicitly supplies a tenant-bound session.
        if tenant_bound:
            snapshot["queue"] = {
                "status": "ok",
                "pending": int(db.query(CrmJob).filter(CrmJob.status == "pending").count()),
                "running": int(db.query(CrmJob).filter(CrmJob.status == "running").count()),
                "failed": int(db.query(CrmJob).filter(CrmJob.status == "failed").count()),
            }

        period_start = quota_period_start()
        try:
            usage_model = SaaSUsage if tenant_bound else PlatformUsage
            ai_cost = db.query(func.coalesce(func.sum(usage_model.used), 0)).filter(
                usage_model.resource == "ai_cost",
                usage_model.period_start == period_start,
            ).scalar()
        except Exception:
            # Development databases may still expose the legacy aggregate
            # table.  Keep this compatibility fallback read-only and never
            # use it for tenant content.
            if tenant_bound:
                raise
            ai_cost = db.query(func.coalesce(func.sum(SaaSUsage.used), 0)).filter(
                SaaSUsage.resource == "ai_cost",
                SaaSUsage.period_start == period_start,
            ).scalar()
        snapshot["ai"]["cost"] = float(Decimal(str(ai_cost or 0)))
        if not tenant_bound:
            snapshot["tenant_migrations"] = {
                "status": "ok",
                "active": int(db.query(TenantRegistry).filter(TenantRegistry.state == "active").count()),
                "migrating": int(db.query(TenantRegistry).filter(TenantRegistry.state == "migrating").count()),
                "failed": int(
                    db.query(TenantRegistry)
                    .filter(TenantRegistry.state.in_(("error", "provision_failed")))
                    .count()
                ),
                "operations_pending": int(
                    db.query(TenantMigrationOperation)
                    .filter(TenantMigrationOperation.state.in_(("migrating", "copied", "verified")))
                    .count()
                ),
            }
    except Exception as error:
        snapshot["database"] = {"status": "error", "error_type": type(error).__name__}
        snapshot["queue"] = {"status": "error", "pending": None, "running": None, "failed": None}
        snapshot["ai"]["status"] = "error"

    # Check the two explicit SaaS databases independently.  No tenant rows or
    # payloads are read; this is reachability-only telemetry for probes.
    for name, engine in (
        ("platform_database", "platform_engine"),
        ("tenant_database", "tenant_engine"),
    ):
        try:
            from app.database import platform_session, tenant_session

            target = getattr(platform_session if name == "platform_database" else tenant_session, engine)
            with target.connect() as connection:
                connection.execute(text("SELECT 1"))
            snapshot[name] = {"status": "ok"}
        except Exception as error:  # noqa: BLE001 - redact details
            snapshot[name] = {"status": "error", "error_type": type(error).__name__}

    circuits = snapshot["provider"]["circuits"]
    if any(item.get("state") == "open" for item in circuits.values()):
        snapshot["provider"]["status"] = "degraded"

    if settings.RATE_LIMIT_ENABLED and settings.RATE_LIMIT_BACKEND.strip().lower() == "redis":
        try:
            from app.middleware.security import RedisRateLimiter

            snapshot["rate_limit"]["status"] = "ok" if RedisRateLimiter(settings.REDIS_URL).ping() else "error"
        except Exception as error:
            snapshot["rate_limit"] = {
                "backend": settings.RATE_LIMIT_BACKEND,
                "status": "error",
                "error_type": type(error).__name__,
            }
    return snapshot


def evaluate_alerts(snapshot: dict) -> list[dict]:
    """Evaluate stable thresholds for an external alerting system."""
    alerts: list[dict] = []
    database = snapshot.get("database", {})
    queue = snapshot.get("queue", {})
    provider = snapshot.get("provider", {})
    rate_limit = snapshot.get("rate_limit", {})
    ai = snapshot.get("ai", {})
    if database.get("status") != "ok":
        alerts.append({"name": "database_unavailable", "severity": "critical", "status": "firing"})
    for database_name in ("platform_database", "tenant_database"):
        if database_name in snapshot and snapshot.get(database_name, {}).get("status") not in {"ok", "unknown"}:
            alerts.append({"name": f"{database_name}_unavailable", "severity": "critical", "status": "firing"})
    pending = queue.get("pending")
    if pending is not None and pending >= settings.ALERT_QUEUE_PENDING_THRESHOLD:
        alerts.append({"name": "queue_backlog", "severity": "warning", "status": "firing", "value": pending, "threshold": settings.ALERT_QUEUE_PENDING_THRESHOLD})
    failed = queue.get("failed")
    if failed is not None and failed > 0:
        alerts.append({"name": "queue_failed_jobs", "severity": "critical", "status": "firing", "value": failed})
    if provider.get("status") != "ok":
        alerts.append({"name": "provider_circuit_open", "severity": "critical", "status": "firing"})
    if rate_limit.get("status") == "error":
        alerts.append({"name": "shared_rate_limit_unavailable", "severity": "critical", "status": "firing"})
    ai_cost = float(ai.get("cost") or 0)
    if ai_cost >= settings.ALERT_AI_COST_THRESHOLD:
        alerts.append({"name": "ai_cost_threshold", "severity": "warning", "status": "firing", "value": ai_cost, "threshold": settings.ALERT_AI_COST_THRESHOLD})
    return alerts


def prometheus_text(snapshot: dict) -> str:
    """Render a small Prometheus exposition without high-cardinality labels."""
    queue = snapshot.get("queue", {})
    lines = [
        "# HELP crm_database_up Database connectivity (1=up).",
        "# TYPE crm_database_up gauge",
        f"crm_database_up {1 if snapshot.get('database', {}).get('status') == 'ok' else 0}",
        "# HELP crm_queue_pending_jobs Pending durable CRM jobs.",
        "# TYPE crm_queue_pending_jobs gauge",
        f"crm_queue_pending_jobs {queue.get('pending') if queue.get('pending') is not None else -1}",
        "# HELP crm_queue_running_jobs Running durable CRM jobs.",
        "# TYPE crm_queue_running_jobs gauge",
        f"crm_queue_running_jobs {queue.get('running') if queue.get('running') is not None else -1}",
        "# HELP crm_queue_failed_jobs Failed durable CRM jobs.",
        "# TYPE crm_queue_failed_jobs gauge",
        f"crm_queue_failed_jobs {queue.get('failed') if queue.get('failed') is not None else -1}",
        "# HELP crm_ai_cost_period Current-period estimated AI cost.",
        "# TYPE crm_ai_cost_period gauge",
        f"crm_ai_cost_period {float(snapshot.get('ai', {}).get('cost') or 0):.4f}",
        "# HELP crm_rate_limit_up Shared rate-limit backend (1=up or disabled).",
        "# TYPE crm_rate_limit_up gauge",
        f"crm_rate_limit_up {1 if snapshot.get('rate_limit', {}).get('status') in {'ok', 'disabled'} else 0}",
    ]
    return "\n".join(lines) + "\n"


def observed_at() -> str:
    return datetime.now(timezone.utc).isoformat()
