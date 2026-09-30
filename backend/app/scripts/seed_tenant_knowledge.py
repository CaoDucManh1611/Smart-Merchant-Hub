"""Seed the configured knowledge dataset into one active shop schema."""

from __future__ import annotations

import argparse

from app.services.knowledge_seed_service import seed_knowledge_base


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed one tenant knowledge base")
    parser.add_argument("business_id", type=int)
    args = parser.parse_args()
    if int(args.business_id) <= 0:
        parser.error("business_id must be a positive integer")
    seed_knowledge_base(business_id=int(args.business_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
