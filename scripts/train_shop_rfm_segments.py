#!/usr/bin/env python3
"""Fit consented, shop-local RFM segmenters through the CRM training service."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
for candidate in (SCRIPT_DIR.parent, SCRIPT_DIR.parent / "backend"):
    if (candidate / "app").is_dir():
        sys.path.insert(0, str(candidate))
        break

from sqlalchemy import select

from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.models.platform_control import TenantRegistry
from app.models.recommendation import RecommendationTrainingRun
from app.services.recommendation_service import (
    SEGMENT_ALGORITHM,
    SEGMENT_MODEL_VERSION,
    train_customer_segments,
)
from app.tenancy.schema import schema_name_for, validate_schema_name


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def targets(business_id: int | None) -> list[tuple[int, str]]:
    query = select(TenantRegistry).where(
        TenantRegistry.state == "active",
        TenantRegistry.feature_enabled.is_(True),
    )
    if business_id is not None:
        query = query.where(TenantRegistry.business_id == business_id)
    query = query.order_by(TenantRegistry.business_id.asc())
    with PlatformSessionLocal() as db:
        registries = db.scalars(query).all()
        rows = []
        for row in registries:
            shop_id = int(row.business_id)
            schema = validate_schema_name(str(row.schema_name))
            if schema != schema_name_for(shop_id):
                raise ValueError(f"tenant_schema_mismatch:{shop_id}")
            rows.append((shop_id, schema))
        return rows


def train_one(business_id: int, schema: str) -> dict[str, Any]:
    with tenant_session(schema) as db:
        run = RecommendationTrainingRun(
            business_id=business_id,
            algorithm=SEGMENT_ALGORITHM,
            status="queued",
            metrics={},
            artifact={
                "model_version": SEGMENT_MODEL_VERSION,
                "trigger": "manual_shop_rfm_training",
                "training_scope": "shop_local_consent_granted_customers",
            },
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        trained = train_customer_segments(db, business_id=business_id, training_run_id=run.id)
        return {
            "business_id": business_id,
            "schema": schema,
            "training_run_id": int(trained.id),
            "status": trained.status,
            "algorithm": trained.algorithm,
            "metrics": trained.metrics if isinstance(trained.metrics, dict) else {},
            "artifact": trained.artifact if isinstance(trained.artifact, dict) else {},
            "error": trained.error_message,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--business-id", type=int)
    target.add_argument("--all-shops", action="store_true")
    args = parser.parse_args()

    selected = targets(args.business_id)
    if args.business_id is not None and not selected:
        parser.error(f"business_id {args.business_id} is not an active, feature-enabled shop")
    report: dict[str, Any] = {
        "started_at_utc": utc_now(),
        "algorithm": SEGMENT_ALGORITHM,
        "model_version": SEGMENT_MODEL_VERSION,
        "training_scope": "each active shop separately; consented customers only",
        "shops_selected": len(selected),
        "results": [],
    }
    for business_id, schema in selected:
        started = utc_now()
        try:
            result = train_one(business_id, schema)
        except Exception as exc:
            result = {
                "business_id": business_id,
                "schema": schema,
                "status": "failed",
                "error": f"{type(exc).__name__}: {str(exc)[:400]}",
            }
        result["started_at_utc"] = started
        result["finished_at_utc"] = utc_now()
        report["results"].append(result)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
    report["finished_at_utc"] = utc_now()
    report["succeeded"] = sum(result.get("status") == "succeeded" for result in report["results"])
    report["failed"] = sum(result.get("status") == "failed" for result in report["results"])
    report["summary"] = {
        "total": len(report["results"]),
        "succeeded": report["succeeded"],
        "failed": report["failed"],
        "model_trained": sum(bool((result.get("metrics") or {}).get("learning_ready")) for result in report["results"]),
        "rules_only_insufficient_data": sum(not bool((result.get("metrics") or {}).get("learning_ready")) for result in report["results"] if result.get("status") == "succeeded"),
    }
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
