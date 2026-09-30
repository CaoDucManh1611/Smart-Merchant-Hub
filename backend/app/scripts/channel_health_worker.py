"""Periodically refresh tenant channel connection health.

This worker intentionally has no provider credentials of its own. Deployments
may inject provider probes through a dedicated adapter, while the default
mode still catches expiry/revocation metadata stored in each tenant schema.
"""

from __future__ import annotations

import argparse
import logging
import time

from app.core.config import settings
from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.services.channel_health import run_scheduled_channel_health


logger = logging.getLogger(__name__)


def run_once() -> list[dict]:
    with PlatformSessionLocal() as platform_db:
        return run_scheduled_channel_health(
            platform_db,
            tenant_session_factory=tenant_session,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh provider health for active tenant channels.")
    parser.add_argument("--once", action="store_true", help="Run one health cycle then exit.")
    parser.add_argument("--poll-seconds", type=float, default=60.0, help="Delay between health cycles.")
    args = parser.parse_args()
    poll_seconds = max(5.0, args.poll_seconds)
    settings.validate_runtime()

    while True:
        try:
            results = run_once()
            degraded = sum(1 for item in results if item.get("status") != "ok")
            logger.info(
                "Channel health cycle complete: shops=%s degraded=%s",
                len(results),
                degraded,
            )
        except Exception:  # noqa: BLE001 - keep the worker alive for the next cycle
            logger.exception("Channel health polling cycle failed")
        if args.once:
            return
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
