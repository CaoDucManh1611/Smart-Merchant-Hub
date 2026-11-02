"""Extract and synchronize structured product records found in shop catalogs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
import unicodedata

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
    components: tuple[str, ...] = ()
    attributes: dict[str, list[str]] | None = None
    status: str = "active"


_TABLE_FIELD_ALIASES = {
    "sku": {"sku", "ma", "ma_sku", "ma_san_pham", "product_code", "item_code", "code"},
    "name": {"name", "ten", "san_pham", "ten_san_pham", "product", "product_name", "item_name"},
    "price": {"price", "price_vnd", "selling_price", "gia", "gia_ban", "don_gia", "unit_price"},
    "stock_quantity": {"stock", "stock_quantity", "ton", "ton_kho", "ton_hien_tai", "so_luong_ton", "quantity_in_stock", "inventory", "available_stock"},
    "description": {"description", "mo_ta", "product_description"},
    "product_url": {"product_url", "product_link", "link_san_pham", "url_san_pham"},
    "name_en": {"name_en", "english_name", "ten_tieng_anh", "ten_san_pham_tieng_anh", "product_name_en"},
    "status": {"status", "trang_thai"},
    "category": {"category", "danh_muc"},
    "suitable_for": {"suitable_for", "phu_hop", "phu_hop_voi", "doi_tuong_phu_hop"},
    "color": {"color", "colors", "colour", "mau", "mau_sac"},
    "size": {"size", "sizes", "kich_thuoc"},
    "volume": {"volume", "capacity", "dung_tich", "the_tich"},
    "keywords": {"keywords", "keyword", "tu_khoa"},
}
_TABLE_FIELD_BY_ALIAS = {
    alias: field for field, aliases in _TABLE_FIELD_ALIASES.items() for alias in aliases
}
_VOLUME_VALUE = re.compile(
    r"\b(?:millilit(?:er|re)s?|ml|cl|dl|lít|lit(?:er|re)?s?)\b",
    re.IGNORECASE,
)


def _normalise_header(value: str) -> str:
    folded = unicodedata.normalize("NFKD", str(value or "").casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char)).replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", "_", folded).strip("_")


def _table_cells(line: str) -> list[str]:
    return [cell.strip().strip("`").strip() for cell in line.strip().strip("|").split("|")]


def _table_header_fields(cells: list[str]) -> dict[str, int]:
    fields: dict[str, int] = {}
    for index, cell in enumerate(cells):
        field = _TABLE_FIELD_BY_ALIAS.get(_normalise_header(cell))
        if field is not None:
            fields.setdefault(field, index)
    return fields


def _is_table_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _extract_table_products(text: str) -> list[CatalogProductRecord]:
    """Read pipe-delimited catalog tables with explicit SKU, price, and stock columns."""
    lines = (text or "").splitlines()
    records: list[CatalogProductRecord] = []
    index = 0
    while index < len(lines):
        if "|" not in lines[index]:
            index += 1
            continue
        headers = _table_cells(lines[index])
        fields = _table_header_fields(headers)
        if not {"sku", "name", "price", "stock_quantity"}.issubset(fields):
            index += 1
            continue

        index += 1
        if index < len(lines) and "|" in lines[index] and _is_table_separator(_table_cells(lines[index])):
            index += 1
        while index < len(lines) and "|" in lines[index]:
            cells = _table_cells(lines[index])
            if _is_table_separator(cells):
                index += 1
                continue
            if {"sku", "name", "price", "stock_quantity"}.issubset(_table_header_fields(cells)):
                break
            index += 1
            required_indexes = (fields["sku"], fields["name"], fields["price"], fields["stock_quantity"])
            if max(required_indexes) >= len(cells):
                continue
            sku = cells[fields["sku"]].strip()
            name = cells[fields["name"]].strip()
            price_text = cells[fields["price"]].strip()
            stock_text = cells[fields["stock_quantity"]].strip()
            if not sku or not name or not price_text or not stock_text:
                continue
            try:
                price = _parse_integer(price_text)
                stock_quantity = _parse_integer(stock_text)
            except (TypeError, ValueError):
                continue

            attributes: dict[str, list[str]] = {}
            core_fields = {"sku", "name", "price", "stock_quantity", "description", "product_url", "name_en", "status"}
            for column, header in enumerate(headers):
                if column >= len(cells) or not cells[column]:
                    continue
                field = _TABLE_FIELD_BY_ALIAS.get(_normalise_header(header))
                if field in core_fields:
                    continue
                key = field or _normalise_header(header)
                if not key:
                    continue
                if key == "size" and _VOLUME_VALUE.search(cells[column]):
                    key = "volume"
                values = (
                    [part.strip() for part in re.split(r"[;,]", cells[column]) if part.strip()]
                    if key in {"size", "color", "keywords"} else [cells[column]]
                )
                attributes[key] = values

            description = cells[fields["description"]] if "description" in fields and fields["description"] < len(cells) else ""
            status = "active"
            if "status" in fields and fields["status"] < len(cells) and cells[fields["status"]]:
                status_value = _normalise_header(cells[fields["status"]])
                if status_value in {"active", "dang_ban", "dang_kinh_doanh", "available", "in_stock", "con_hang", "het_hang", "out_of_stock"}:
                    status = "active"
                elif status_value in {"inactive", "archived", "deleted", "ngung_ban", "ngung_kinh_doanh"}:
                    status = "archived"
                else:
                    continue
            elif "status" in fields:
                continue
            records.append(CatalogProductRecord(
                sku=sku,
                name=name,
                price=Decimal(price),
                stock_quantity=stock_quantity,
                description=description,
                aliases=tuple(_build_aliases(name)),
                attributes=attributes or None,
                status=status,
            ))
    return records


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
        components = _extract_combo_components(body)
        attributes = _extract_attributes(body)
        records.append(CatalogProductRecord(
            sku=sku,
            name=name,
            price=Decimal(price),
            stock_quantity=stock_quantity,
            description=body,
            aliases=tuple(aliases),
            components=tuple(components),
            attributes=attributes,
        ))
    records.extend(_extract_table_products(text))
    unique: dict[str, CatalogProductRecord] = {}
    for record in records:
        key = record.sku.casefold()
        previous = unique.get(key)
        if previous is None:
            unique[key] = record
            continue
        attributes = {**(record.attributes or {}), **(previous.attributes or {})}
        unique[key] = CatalogProductRecord(
            sku=previous.sku,
            name=previous.name,
            price=previous.price,
            stock_quantity=previous.stock_quantity,
            description=previous.description or record.description,
            aliases=tuple(dict.fromkeys((*previous.aliases, *record.aliases))),
            components=tuple(dict.fromkeys((*previous.components, *record.components))),
            attributes=attributes or None,
            status=previous.status,
        )
    return list(unique.values())


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


def _extract_combo_components(body: str) -> list[str]:
    """Extract component names without guessing their product ids."""
    match = re.search(
        r"(?:gồm|bao\s+gồm)\s*:?\s*(.+?)(?=(?:\.\s*(?:giá|tồn|ton)|;\s*(?:giá|tồn|ton)|$))",
        body,
        flags=re.IGNORECASE,
    )
    if match is None:
        return []
    segment = " ".join(match.group(1).split()).strip(" .;:")
    if not segment:
        return []
    segment = re.sub(r"\s+và\s+", ", ", segment, flags=re.IGNORECASE)
    components = []
    for item in re.split(r"[,;]", segment):
        cleaned = re.sub(r"^[-–•]\s*", "", item).strip(" .;:")
        if cleaned:
            components.append(cleaned)
    return list(dict.fromkeys(components))


def _extract_attributes(body: str) -> dict[str, list[str]]:
    """Extract explicitly provided product facets without guessing values."""
    patterns = {
        "suitable_for": r"(?:phù hợp|dành cho|đối tượng)\s*[:\-]?\s*([^.;]+)",
        "colors": r"(?:màu|màu sắc)\s*[:\-]\s*([^.;]+)",
        "sizes": r"(?:kích thước|size)\s*[:\-]\s*([^.;]+)",
        "keywords": r"(?:từ khóa|keywords?)\s*[:\-]\s*([^.;]+)",
    }
    attributes: dict[str, list[str]] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, body or "", flags=re.IGNORECASE)
        if match is None:
            continue
        values = re.split(r",|\s+và\s+|\s*\|\s*", match.group(1), flags=re.IGNORECASE)
        cleaned = [" ".join(value.strip().split()) for value in values if value.strip()]
        if cleaned:
            attributes[key] = list(dict.fromkeys(cleaned))
    return attributes


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
                status=record.status,
                metadata_={
                    "aliases": list(record.aliases),
                    "catalog_source_document_id": source_document_id,
                    "catalog_source": "knowledge_document",
                    **({"components": list(record.components)} if record.components else {}),
                    **({"attributes": record.attributes} if record.attributes else {}),
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
            product.status = record.status
            metadata.update({
                "aliases": list(record.aliases),
                "catalog_source_document_id": source_document_id,
                "catalog_source": "knowledge_document",
            })
            if record.components:
                metadata["components"] = list(record.components)
            if record.attributes:
                metadata["attributes"] = record.attributes
            product.metadata_ = metadata
            synced.append(product)
        elif source_id is None:
            # Do not overwrite manually managed price/stock; only enrich the
            # record with aliases and missing explicit facets from the document.
            aliases = list(dict.fromkeys([*(metadata.get("aliases") or []), *record.aliases]))
            attributes = dict(metadata.get("attributes") or {})
            for key, value in (record.attributes or {}).items():
                attributes.setdefault(key, value)
            if aliases != metadata.get("aliases") or attributes != metadata.get("attributes"):
                product.metadata_ = {**metadata, "aliases": aliases, **({"attributes": attributes} if attributes else {})}
            # Even an unchanged canonical product needs its matching document
            # chunks linked so exact catalog filters can run before LIMIT.
            synced.append(product)
        else:
            # The product is already owned by another source document. Preserve
            # that canonical row, but link this exact-SKU evidence to it.
            synced.append(product)
    return synced
