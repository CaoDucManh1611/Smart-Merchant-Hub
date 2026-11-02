"""Backfill missing product and appointment-service catalog entries per tenant.

Dry-run is the default. Use --apply to insert only missing catalog records.
The script never changes existing catalog rows and uses registered tenant
schemas on the configured tenant database.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text

from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.models.industry_modules import AppointmentService
from app.models.platform_control import TenantRegistry
from app.models.recommendation_catalog import RecommendationCatalogEntry
from app.models.sales import Product
from app.services.recommendation_catalog_service import (
    sync_appointment_service_catalog_entry,
    sync_product_catalog_entry,
)
from app.tenancy.schema import schema_name_for, validate_schema_name


_MIGRATED_STATES = {"active", "ready", "disabled"}


def _exact_chunk_ids(db, business_id: int, token: str) -> list[int]:
    """Find ready tenant chunks that mention a whole SKU/service name."""
    value = str(token or "").strip()
    if not value:
        return []
    pattern = r"(^|[^[:alnum:]_-])" + re.escape(value) + r"([^[:alnum:]_-]|$)"
    rows = db.execute(
        text("""
            SELECT dc.id
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE d.business_id = :business_id
              AND d.status = 'ready'
              AND COALESCE(dc.content, '') ~* :pattern
            ORDER BY dc.id
        """),
        {"business_id": business_id, "pattern": pattern},
    ).scalars().all()
    return [int(value) for value in rows]


def _tenant_rows() -> list[tuple[int, str, str]]:
    with PlatformSessionLocal() as db:
        registries = db.scalars(
            select(TenantRegistry).order_by(TenantRegistry.business_id)
        ).all()
        rows = []
        for row in registries:
            schema = validate_schema_name(row.schema_name)
            if schema != schema_name_for(int(row.business_id)):
                raise ValueError(f"tenant registry schema mismatch for business {row.business_id}")
            if str(row.state).lower() in _MIGRATED_STATES:
                rows.append((int(row.business_id), schema, str(row.state)))
        return rows


def run(*, apply: bool = False) -> dict:
    results = []
    for business_id, schema, state in _tenant_rows():
        result = {
            "business_id": business_id,
            "schema": schema,
            "registry_state": state,
            "status": "ok",
            "products": 0,
            "services": 0,
            "existing_catalog_entries": 0,
            "missing_products": 0,
            "missing_services": 0,
            "inserted_products": 0,
            "inserted_services": 0,
            "mapped_product_chunks": 0,
            "mapped_service_chunks": 0,
        }
        try:
            with tenant_session(schema) as db:
                products = db.scalars(
                    select(Product).where(Product.business_id == business_id).order_by(Product.id)
                ).all()
                services = db.scalars(
                    select(AppointmentService)
                    .where(AppointmentService.business_id == business_id)
                    .order_by(AppointmentService.id)
                ).all()
                entries = db.scalars(
                    select(RecommendationCatalogEntry).where(
                        RecommendationCatalogEntry.business_id == business_id
                    )
                ).all()
                existing = {(row.object_type, row.external_id) for row in entries}
                missing_products = [row for row in products if ("product", str(row.id)) not in existing]
                missing_services = [row for row in services if ("service", str(row.id)) not in existing]
                result.update(
                    products=len(products),
                    services=len(services),
                    existing_catalog_entries=len(entries),
                    missing_products=len(missing_products),
                    missing_services=len(missing_services),
                )
                if apply:
                    for product in missing_products:
                        metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
                        explicit_ids = metadata.get("catalog_chunk_ids")
                        chunk_ids = set(int(value) for value in explicit_ids if str(value).isdigit()) if isinstance(explicit_ids, list) else set()
                        chunk_ids.update(_exact_chunk_ids(db, business_id, product.sku))
                        sync_product_catalog_entry(
                            db,
                            product,
                            source="catalog_backfill_2026_11_01",
                            document_chunk_ids=sorted(chunk_ids),
                        )
                        result["inserted_products"] += 1
                        result["mapped_product_chunks"] += len(chunk_ids)
                    for service in missing_services:
                        sync_appointment_service_catalog_entry(db, service, source="catalog_backfill_2026_11_01")
                        # Service sync has no chunk-link argument; skip automatic links until the
                        # source service model has an explicit, reviewable mapping field.
                    result["inserted_services"] = len(missing_services)
        except Exception as error:  # report a shop-local failure, continue the remaining tenants
            result.update(status="error", error_type=type(error).__name__)
        results.append(result)
    return {
        "mode": "apply" if apply else "dry_run",
        "tenant_count": len(results),
        "ok_tenant_count": sum(row["status"] == "ok" for row in results),
        "error_tenant_count": sum(row["status"] != "ok" for row in results),
        "totals": {
            key: sum(int(row.get(key, 0)) for row in results)
            for key in (
                "products", "services", "existing_catalog_entries", "missing_products",
                "missing_services", "inserted_products", "inserted_services",
                "mapped_product_chunks", "mapped_service_chunks",
            )
        },
        "tenants": results,
        "notes": [
            "Reads only registered tenant schemas from the configured local platform/tenant databases.",
            "Default mode is read-only; --apply inserts only missing product/service entries.",
            "Existing catalog entries are never overwritten by this script.",
            "Product chunks are linked only by exact SKU or explicit metadata catalog_chunk_ids.",
            "Appointment-service chunk links are not inferred; service data has no explicit mapping field.",
            "Rental offers have no canonical source table/model in this checkout and are not backfilled.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="insert missing catalog rows")
    parser.add_argument("--output", type=Path, help="also write JSON summary to this path")
    args = parser.parse_args()
    report = run(apply=args.apply)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if report["error_tenant_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
