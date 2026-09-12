"""Deterministic product/combo pricing answers for commerce conversations."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

from sqlalchemy.orm import Session

from app.models.sales import Product
from app.services.product_resolver import normalize_product_text, resolve_product


COMBO_COMPARISON_TERMS = (
    "mua le",
    "mua tung mon",
    "mon le",
    "mon trong combo",
    "mua rieng",
    "gia le",
    "le bao nhieu",
    "re hon",
    "tiet kiem",
    "chenh gia",
    "so voi mua le",
)


def is_combo_comparison_request(text: str | None) -> bool:
    folded = normalize_product_text(text)
    return (
        ("combo" in folded or re.search(r"\bbo\b", folded) is not None or "mon le" in folded)
        and any(term in folded for term in COMBO_COMPARISON_TERMS)
    )


def _is_combo(product: Product) -> bool:
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    name = normalize_product_text(product.name)
    description = normalize_product_text(product.description)
    return bool(
        "combo" in name
        or name.startswith("bo ")
        or "combo" in description
        or "gom " in description
        or metadata.get("components")
        or metadata.get("bundle_components")
    )


def _component_specs(combo: Product) -> list[tuple[object, int]]:
    metadata = combo.metadata_ if isinstance(combo.metadata_, dict) else {}
    raw = metadata.get("components") or metadata.get("bundle_components") or metadata.get("items")
    specs: list[tuple[object, int]] = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            quantity = 1
            value: object = item
            if isinstance(item, dict):
                value = item.get("product_id") or item.get("sku") or item.get("name")
                try:
                    quantity = max(int(item.get("quantity") or 1), 1)
                except (TypeError, ValueError):
                    quantity = 1
            if value:
                specs.append((value, quantity))
    if specs:
        return specs

    description = str(combo.description or "")
    match = re.search(
        r"(?:gồm|bao\s+gồm)\s*:?\s*(.+?)(?=(?:\.\s*(?:giá|tồn|ton)|;\s*(?:giá|tồn|ton)|$))",
        description,
        flags=re.IGNORECASE,
    )
    if match is None:
        return []
    segment = re.sub(r"\s+và\s+", ", ", " ".join(match.group(1).split()), flags=re.IGNORECASE)
    return [(part.strip(" .;:"), 1) for part in re.split(r"[,;]", segment) if part.strip(" .;:")]


def _resolve_component(
    db: Session,
    *,
    business_id: int,
    combo: Product,
    reference: object,
) -> Product | None:
    if isinstance(reference, int) or (isinstance(reference, str) and reference.isdigit()):
        product = db.query(Product).filter(
            Product.id == int(reference),
            Product.business_id == business_id,
            Product.status == "active",
        ).first()
    else:
        value = str(reference).strip()
        product = db.query(Product).filter(
            Product.business_id == business_id,
            Product.status == "active",
            Product.sku == value,
        ).first()
        if product is None:
            product = resolve_product(db, business_id=business_id, text=value)
    if product is combo or (product is not None and product.id == combo.id):
        return None
    return product


def _format_vnd(value: Decimal | int | float | str) -> str:
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0")
    return f"{amount:,.0f}".replace(",", ".")


def combo_price_comparison_reply(
    db: Session,
    *,
    business_id: int,
    text: str,
    conversation_id: int | None = None,
) -> str | None:
    """Return a factual combo-vs-individual-price answer when applicable."""
    if not is_combo_comparison_request(text):
        return None

    combo = resolve_product(
        db,
        business_id=business_id,
        text=text,
        conversation_id=conversation_id,
    )
    if combo is None or not _is_combo(combo):
        candidates = db.query(Product).filter(
            Product.business_id == business_id,
            Product.status == "active",
        ).order_by(Product.id.asc()).all()
        combo = next((candidate for candidate in candidates if _is_combo(candidate)), None)
    if combo is None:
        return "Mình chưa tìm thấy combo phù hợp để so sánh giá. Bạn cho mình tên combo cụ thể nhé."

    components: list[tuple[Product, int]] = []
    for reference, quantity in _component_specs(combo):
        product = _resolve_component(
            db,
            business_id=business_id,
            combo=combo,
            reference=reference,
        )
        if product is None:
            return (
                f"Mình đã thấy {combo.name} giá {_format_vnd(combo.price)} đồng, "
                "nhưng catalog chưa đủ giá từng món thành phần nên chưa thể tính chính xác phần chênh lệch."
            )
        components.append((product, quantity))

    if not components:
        return (
            f"Mình đã thấy {combo.name} giá {_format_vnd(combo.price)} đồng, "
            "nhưng catalog chưa có danh sách món thành phần để so sánh giá lẻ."
        )

    retail_total = sum(Decimal(product.price or 0) * quantity for product, quantity in components)
    combo_price = Decimal(combo.price or 0)
    savings = retail_total - combo_price
    component_text = ", ".join(
        f"{quantity} {product.name} ({_format_vnd(product.price)} đồng)"
        for product, quantity in components
    )
    if savings > 0 and retail_total > 0:
        percent = (savings / retail_total * Decimal("100")).quantize(Decimal("0.1"))
        percent_text = str(percent).replace(".", ",")
        return (
            f"Nếu mua lẻ gồm {component_text} thì khoảng {_format_vnd(retail_total)} đồng. "
            f"Mua {combo.name} là {_format_vnd(combo_price)} đồng, "
            f"rẻ hơn {_format_vnd(savings)} đồng ({percent_text}%)."
        )
    if savings == 0:
        return (
            f"Các món trong {combo.name} mua lẻ cũng khoảng {_format_vnd(retail_total)} đồng, "
            "nên hiện chưa có chênh lệch giá."
        )
    return (
        f"Nếu mua lẻ gồm {component_text} thì khoảng {_format_vnd(retail_total)} đồng; "
        f"giá combo hiện là {_format_vnd(combo_price)} đồng, cao hơn {_format_vnd(-savings)} đồng."
    )
