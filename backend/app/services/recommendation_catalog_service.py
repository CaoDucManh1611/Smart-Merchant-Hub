"""Tenant catalog synchronization for product, service and rental offers."""
from __future__ import annotations
import unicodedata
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Iterable
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session
from app.models.document import DocumentChunk
from app.models.industry_modules import AppointmentService
from app.models.recommendation_catalog import RecommendationCatalogAttribute, RecommendationCatalogChunkMapping, RecommendationCatalogEntry
from app.models.sales import Product

OBJECT_TYPES = {"product", "service", "rental"}
_VOLUME_ATTRIBUTE_KEYS = {"volume", "capacity", "dung_tich", "dung_tích", "the_tich", "thể_tích"}
_EXPLICIT_VOLUME = re.compile(
    r"(?:dung\s+t[ií]ch|th[eể]\s+t[ií]ch|volume|capacity)\s*[:\-]?\s*"
    r"(?P<value>\d+(?:[.,]\d+)?\s*(?:millilit(?:er|re)s?|ml|cl|dl|lít|lit(?:er|re)?s?))\b",
    re.IGNORECASE,
)


def normalize(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())
def _key(value: str) -> str:
    result = normalize(value).replace(" ", "_")
    if not result or len(result) > 100: raise ValueError("attribute key must be 1..100 chars")
    return result
def _attributes(values: dict[str, Any] | None) -> list[RecommendationCatalogAttribute]:
    rows: dict[tuple[str, str], RecommendationCatalogAttribute] = {}
    for key, raw in (values or {}).items():
        for value in (raw if isinstance(raw, (list, tuple, set)) else [raw]):
            if value is None:
                continue
            if isinstance(value, bool):
                kind, norm, text, num, boolean, day = "boolean", str(value).casefold(), None, None, value, None
            elif isinstance(value, (int, float, Decimal)):
                num = Decimal(str(value))
                kind, norm, text, boolean, day = "number", format(num.normalize(), "f"), None, None, None
            elif isinstance(value, (date, datetime)):
                day = value.date() if isinstance(value, datetime) else value
                kind, norm, text, num, boolean = "date", day.isoformat(), None, None, None
            else:
                text = unicodedata.normalize("NFKC", str(value)).strip()
                if not text:
                    continue
                kind, norm, num, boolean, day = "text", normalize(text), None, None, None
            row = RecommendationCatalogAttribute(
                key_norm=_key(key),
                value_type=kind,
                normalized_value=norm[:255],
                text_value=text,
                number_value=num,
                boolean_value=boolean,
                date_value=day,
            )
            rows[(row.key_norm, row.normalized_value)] = row
    return list(rows.values())


def _sync_attributes(entry: RecommendationCatalogEntry, values: dict[str, Any] | None) -> None:
    wanted = {
        (row.key_norm, row.normalized_value): row
        for row in _attributes(values)
    }
    existing = {
        (row.key_norm, row.normalized_value): row
        for row in entry.attributes
    }
    for key, row in existing.items():
        if key not in wanted:
            entry.attributes.remove(row)
    for key, row in wanted.items():
        current = existing.get(key)
        if current is None:
            entry.attributes.append(row)
            continue
        current.value_type = row.value_type
        current.text_value = row.text_value
        current.number_value = row.number_value
        current.boolean_value = row.boolean_value
        current.date_value = row.date_value


def sync_catalog_entry(db: Session, *, business_id: int, object_type: str, external_id: str, name: str, description: str | None = None, sku: str | None = None, status: str = "active", availability: str = "in_stock", stock_quantity: Any = None, price: Any = None, currency: str | None = None, attributes: dict[str, Any] | None = None, document_chunk_ids: Iterable[int] | None = None, source: str = "catalog_sync", metadata: dict[str, Any] | None = None) -> RecommendationCatalogEntry:
    """Upsert offer and replace attrs/chunk links; caller owns transaction commit."""
    kind = normalize(object_type)
    if kind not in OBJECT_TYPES: raise ValueError("object_type must be product, service, or rental")
    external_id, name = str(external_id).strip(), str(name).strip()
    if business_id <= 0 or not external_id or not name: raise ValueError("business_id, external_id and name are required")
    entry = db.scalar(select(RecommendationCatalogEntry).where(RecommendationCatalogEntry.business_id == business_id, RecommendationCatalogEntry.object_type == kind, RecommendationCatalogEntry.external_id == external_id))
    if entry is None:
        entry = RecommendationCatalogEntry(business_id=business_id, object_type=kind, external_id=external_id, revision=1); db.add(entry)
    else: entry.revision = (entry.revision or 0) + 1
    entry.name, entry.description = name, description
    entry.sku_norm = normalize(sku)[:120] if sku else None
    entry.status, entry.availability = normalize(status), normalize(availability)
    entry.stock_quantity = Decimal(str(stock_quantity)) if stock_quantity is not None else None
    entry.price = Decimal(str(price)) if price is not None else None
    entry.currency, entry.source, entry.metadata_ = (currency.upper()[:3] if currency else None), str(source)[:60], metadata or {}
    _sync_attributes(entry, attributes)
    db.flush()
    if document_chunk_ids is not None:
        wanted = {int(item) for item in document_chunk_ids if int(item) > 0}
        db.execute(delete(RecommendationCatalogChunkMapping).where(RecommendationCatalogChunkMapping.catalog_entry_id == entry.id))
        for chunk_id in sorted(wanted):
            # Reject cross-shop or nonexistent chunks before creating the FK.
            owned = db.scalar(select(DocumentChunk.id).join(DocumentChunk.document).where(
                DocumentChunk.id == chunk_id,
                DocumentChunk.document.has(business_id=business_id),
            ))
            if owned is None:
                raise ValueError("document chunk must belong to this shop")
            db.add(RecommendationCatalogChunkMapping(catalog_entry_id=entry.id, document_chunk_id=chunk_id, mapping_type="primary"))
    db.flush()
    return entry


def sync_product_catalog_entry(db: Session, product: Product, *, source: str = "product_sync", document_chunk_ids: Iterable[int] | None = None) -> RecommendationCatalogEntry:
    """Mirror a canonical shop product after its source row has been flushed."""
    db.flush()
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    attributes = dict(metadata.get("attributes")) if isinstance(metadata.get("attributes"), dict) else {}
    has_volume = any(
        normalize(key).replace(" ", "_") in _VOLUME_ATTRIBUTE_KEYS and value not in (None, "", [])
        for key, value in attributes.items()
    )
    if not has_volume:
        match = _EXPLICIT_VOLUME.search(" ".join((product.name or "", product.description or "")))
        if match:
            attributes["volume"] = match.group("value")
    reserved = int(product.reserved_quantity or 0)
    available_stock = int(product.stock_quantity or 0) - reserved
    entry = sync_catalog_entry(
        db,
        business_id=int(product.business_id),
        object_type="product",
        external_id=str(product.id),
        name=product.name,
        description=product.description,
        sku=product.sku,
        status="active" if product.status == "active" else str(product.status or "inactive"),
        availability="in_stock" if available_stock > 0 else "out_of_stock",
        stock_quantity=max(0, available_stock),
        price=product.price,
        attributes=attributes,
        document_chunk_ids=(document_chunk_ids if document_chunk_ids is not None else metadata.get("catalog_chunk_ids")) if document_chunk_ids is not None or isinstance(metadata.get("catalog_chunk_ids"), list) else None,
        source=source,
        metadata={"product_status": product.status, "reserved_quantity": reserved},
    )
    product.metadata_ = {**metadata, "recommendation_catalog_revision": int(entry.revision)}
    db.flush()
    return entry


def sync_appointment_service_catalog_entry(db: Session, service: AppointmentService, *, source: str = "service_sync") -> RecommendationCatalogEntry:
    db.flush()
    return sync_catalog_entry(
        db,
        business_id=int(service.business_id),
        object_type="service",
        external_id=str(service.id),
        name=service.name,
        description=service.description,
        status="active" if service.is_active else "inactive",
        availability="available" if service.is_active else "unavailable",
        price=service.price,
        attributes={"duration_minutes": service.duration_minutes},
        source=source,
    )
def get_available_catalog_entries(db: Session, *, business_id: int, candidate_ids: Iterable[int], object_type: str | None = None, live_availability_reader: Callable[[str, str], bool] | None = None) -> list[RecommendationCatalogEntry]:
    """Return only offers still available in their authoritative shop tables."""
    ids = {int(value) for value in candidate_ids}
    if not ids: return []
    stmt = select(RecommendationCatalogEntry).where(RecommendationCatalogEntry.business_id == business_id, RecommendationCatalogEntry.id.in_(ids), RecommendationCatalogEntry.status == "active", RecommendationCatalogEntry.availability.not_in(("unavailable", "out_of_stock")), or_(RecommendationCatalogEntry.stock_quantity.is_(None), RecommendationCatalogEntry.stock_quantity > 0))
    if object_type:
        kind = normalize(object_type)
        if kind not in OBJECT_TYPES: return []
        stmt = stmt.where(RecommendationCatalogEntry.object_type == kind)
    rows = list(db.scalars(stmt))
    if live_availability_reader is not None:
        return [row for row in rows if live_availability_reader(row.object_type, row.external_id)]
    available = []
    for row in rows:
        if row.object_type == "product" and row.external_id.isdigit():
            product = db.scalar(select(Product).where(Product.id == int(row.external_id), Product.business_id == business_id))
            if product is not None and product.status == "active" and int(product.stock_quantity or 0) > int(product.reserved_quantity or 0):
                available.append(row)
        elif row.object_type == "service" and row.external_id.isdigit():
            service = db.scalar(select(AppointmentService).where(AppointmentService.id == int(row.external_id), AppointmentService.business_id == business_id))
            if service is not None and service.is_active:
                available.append(row)
        # Rental availability is source-specific; fail closed unless the caller
        # supplied a reader for the shop's authoritative rental system.
    return available
