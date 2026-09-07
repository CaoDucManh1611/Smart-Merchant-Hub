"""Run the persistent CRM job dispatcher as a small Docker worker."""

from __future__ import annotations

import argparse
import logging
import time

from app.core.config import settings
from app.database.session import SessionLocal
from app.services.crm_job_worker import dispatch_all_crm_jobs


logger = logging.getLogger(__name__)


def run_once() -> int:
    with SessionLocal() as db:
        return dispatch_all_crm_jobs(db)


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
