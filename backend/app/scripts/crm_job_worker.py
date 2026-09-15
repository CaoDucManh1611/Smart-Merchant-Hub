"""Run the persistent CRM job dispatcher as a small Docker worker."""

from __future__ import annotations

import argparse
import logging
import time

from app.core.config import settings
from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.services.crm_job_worker import dispatch_all_crm_jobs
from app.services.channel_health import run_scheduled_channel_health


logger = logging.getLogger(__name__)
_last_health_check = 0.0


def run_once() -> int:
    global _last_health_check
    with PlatformSessionLocal() as platform_db:
        processed = dispatch_all_crm_jobs(
            platform_db,
            tenant_session_factory=tenant_session,
        )
        now = time.monotonic()
        interval = max(5, int(settings.CHANNEL_HEALTH_INTERVAL_SECONDS))
        if now - _last_health_check >= interval:
            try:
                health = run_scheduled_channel_health(
                    platform_db,
                    tenant_session_factory=tenant_session,
                )
                degraded = sum(1 for item in health if item.get("status") != "ok")
                logger.info(
                    "Channel health cycle complete: shops=%s degraded=%s",
                    len(health),
                    degraded,
                )
            except Exception:  # noqa: BLE001 - jobs continue if health is unavailable
                logger.exception("Channel health cycle failed")
            finally:
                _last_health_check = now
        return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch due CRM ticket and workflow jobs.")
    parser.add_argument("--once", action="store_true", help="Run one polling cycle then exit.")
    parser.add_argument("--poll-seconds", type=float, default=5.0, help="Delay between polling cycles.")
    args = parser.parse_args()
    poll_seconds = max(0.5, args.poll_seconds)
    settings.validate_runtime()

    while True:
        try:
            processed = run_once()
            if processed:
                logger.info("CRM job worker processed %s job(s)", processed)
        except Exception:  # noqa: BLE001 - keep the worker alive for the next retry cycle
            logger.exception("CRM job worker polling cycle failed")
        if args.once:
            return
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
