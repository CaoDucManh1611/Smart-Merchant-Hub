"""Operator recovery when a restore was interrupted and HTTP stays in maintenance."""

import argparse
import json

from app.services.platform_backup import run_job, read_job, start_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_id")
    parser.add_argument("--confirm", required=True, choices=["KHÔI PHỤC"])
    args = parser.parse_args()
    job, mutex = start_job("restore", actor_id=0, backup_id=args.backup_id)
    run_job(job, mutex)
    result = read_job(job["id"])
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "succeeded" else 1)


if __name__ == "__main__":
    main()
