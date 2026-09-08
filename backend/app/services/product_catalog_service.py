"""Extract and synchronize structured product records found in shop catalogs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

from sqlalchemy.orm import Session

from app.models.sales import Product


@dataclass(frozen=True)
class CatalogProductRecord:
    sku: str
    name: str
    price: Decimal
    stock_quantity: int
    description: str
    aliases: tuple[str, ...]


def extract_catalog_products(text: str) -> list[CatalogProductRecord]:
    records: list[CatalogProductRecord] = []
    pattern = re.compile(
        r"^\s*-\s*(?P<name>.+?)\s*\(\s*SKU\s+(?P<sku>[A-Za-z0-9][A-Za-z0-9_.-]*)\s*\)\s*:\s*(?P<body>.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    for match in pattern.finditer(text or ""):
        name = " ".join(match.group("name").split())
        sku = match.group("sku").strip()
        body = " ".join(match.group("body").split())
        combo_price = re.search(
            r"giá\s+combo\s*[:\-]?\s*([\d][\d.,]*)",
            body,
            flags=re.IGNORECASE,
        )
        price_match = combo_price or re.search(
            r"giá(?:\s+niêm\s+yết)?\s*[:\-]?\s*([\d][\d.,]*)",
            body,
            flags=re.IGNORECASE,
        )
        stock_match = re.search(
            r"tồn\s+kho(?:\s+[^:.;]+)?\s*:\s*([\d][\d.,]*)",
            body,
            flags=re.IGNORECASE,
        )
        if price_match is None or stock_match is None:
            continue

        price = _parse_integer(price_match.group(1))
        stock_quantity = _parse_integer(stock_match.group(1))
        aliases = _build_aliases(name)
        records.append(CatalogProductRecord(
            sku=sku,
            name=name,
            price=Decimal(price),
            stock_quantity=stock_quantity,
            description=body,
            aliases=tuple(aliases),
        ))
    return records


def _parse_integer(value: str) -> int:
    digits = re.sub(r"[^0-9]", "", value or "")
    return int(digits or 0)


def _build_aliases(name: str) -> list[str]:
    aliases = [name]
    folded = name.casefold()
    if folded.startswith("combo "):
        remainder = name[6:].strip()
        if remainder:
            aliases.extend((f"combo {remainder}", f"bộ {remainder}"))
            if "cơ bản" in remainder.casefold():
                aliases.append("combo cơ bản")
    return list(dict.fromkeys(aliases))


def sync_catalog_products(
    db: Session,
    *,
    business_id: int,
    source_document_id: int,
    text: str,
):
    synced: list[Product] = []
    for record in extract_catalog_products(text):
        product = db.query(Product).filter(
            Product.business_id == business_id,
            Product.sku == record.sku,
        ).first()
        if product is None:
            product = Product(
                business_id=business_id,
                sku=record.sku,
                name=record.name,
                description=record.description,
                price=record.price,
                stock_quantity=record.stock_quantity,
                status="active",
                metadata_={
                    "aliases": list(record.aliases),
                    "catalog_source_document_id": source_document_id,
                    "catalog_source": "knowledge_document",
                },
            )
            db.add(product)
            synced.append(product)
            continue

        metadata = dict(product.metadata_ or {})
        source_id = metadata.get("catalog_source_document_id")
        if source_id in (None, source_document_id) and metadata.get("catalog_source") == "knowledge_document":
            product.name = record.name
            product.description = record.description
            product.price = record.price
            product.stock_quantity = record.stock_quantity
            metadata.update({
                "aliases": list(record.aliases),
                "catalog_source_document_id": source_document_id,
                "catalog_source": "knowledge_document",
            })
            product.metadata_ = metadata
            synced.append(product)
        elif source_id is None:
            # Do not overwrite manually managed price/stock; only enrich the
            # record with aliases so future queries can resolve it.
            aliases = list(dict.fromkeys([*(metadata.get("aliases") or []), *record.aliases]))
            if aliases != metadata.get("aliases"):
                product.metadata_ = {**metadata, "aliases": aliases}
                synced.append(product)
    return synced
