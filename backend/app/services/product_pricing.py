"""Deterministic product/combo pricing answers for commerce conversations."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

from sqlalchemy.orm import Session

from app.models.sales import Product
from app.services.product_resolver import normalize_product_text, product_aliases, resolve_product


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


def _available(product: Product) -> int:
    return max(int(product.stock_quantity or 0) - int(product.reserved_quantity or 0), 0)


def _requested_component(
    text: str,
    components: list[tuple[Product, int]],
) -> tuple[Product, int] | None:
    """Find the explicitly named bundle item, if the customer named one.

    A combo has one price, so a request such as "mua lẻ sữa rửa mặt" must
    not silently turn into a quote for the whole bundle.  We use the same
    catalog aliases as product resolution and choose the longest match to
    avoid a generic alias (for example ``serum``) shadowing a more specific
    product name.
    """
    folded = normalize_product_text(text)
    matches: list[tuple[int, int, Product, int]] = []
    for product, quantity in components:
        for alias in product_aliases(product):
            normalized = normalize_product_text(alias)
            if not normalized:
                continue
            if normalized in folded:
                matches.append((len(normalized), -int(product.id or 0), product, quantity))
                continue
            # Mirror the resolver's conservative abbreviated-name behavior:
            # "sữa rửa mặt" should still identify "sữa rửa mặt dịu nhẹ".
            alias_tokens = {token for token in normalized.split() if len(token) >= 2}
            query_tokens = set(folded.split())
            if len(alias_tokens) >= 2:
                matched = len(alias_tokens & query_tokens)
                if matched >= 2 and matched / len(alias_tokens) >= 0.5:
                    matches.append((matched * 100 + len(normalized), -int(product.id or 0), product, quantity))
    if not matches:
        return None
    _length, _id, product, quantity = max(matches)
    return product, quantity


def _alternative_hint(db: Session, *, business_id: int, excluded_ids: set[int]) -> str:
    candidates = db.query(Product).filter(
        Product.business_id == business_id,
        Product.status == "active",
        Product.stock_quantity > Product.reserved_quantity,
        ~Product.id.in_(excluded_ids),
    ).order_by(Product.price.asc(), Product.id.asc()).all()
    alternatives = [product for product in candidates if not _is_combo(product)][:3]
    if not alternatives:
        return ""
    choices = ", ".join(
        f"{product.name} ({_format_vnd(product.price)} đồng, còn {_available(product)})"
        for product in alternatives
    )
    return f" Gợi ý thay thế đang còn hàng: {choices}."


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
                + _alternative_hint(db, business_id=business_id, excluded_ids={combo.id})
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
    requested_component = _requested_component(text, components)
    component_text = ", ".join(
        f"{quantity} {product.name} ({_format_vnd(product.price)} đồng)"
        for product, quantity in components
    )
    availability_note = ""
    if _available(combo) <= 0 or any(_available(product) < quantity for product, quantity in components):
        excluded_ids = {combo.id}
        if _available(combo) > 0:
            excluded_ids.update(product.id for product, _quantity in components)
        availability_note = (
            " Hiện combo hoặc một món thành phần không đủ tồn kho."
            + _alternative_hint(
                db,
                business_id=business_id,
                excluded_ids=excluded_ids,
            )
        )
    if savings > 0 and retail_total > 0:
        percent = (savings / retail_total * Decimal("100")).quantize(Decimal("0.1"))
        percent_text = str(percent).replace(".", ",")
        component_note = ""
        if requested_component is not None:
            product, quantity = requested_component
            component_retail = Decimal(product.price or 0) * quantity
            allocated_discount = (savings * component_retail / retail_total).quantize(Decimal("1"))
            allocated_combo_price = component_retail - allocated_discount
            component_note = (
                f" {product.name} mua lẻ là {_format_vnd(component_retail)} đồng. "
                f"Catalog chưa tách giá combo theo từng món; nếu phân bổ theo tỷ trọng, "
                f"phần ưu đãi của món này khoảng {_format_vnd(allocated_discount)} đồng "
                f"(giá quy đổi khoảng {_format_vnd(allocated_combo_price)} đồng)."
            )
        return (
            f"Nếu mua lẻ gồm {component_text} thì khoảng {_format_vnd(retail_total)} đồng."
            f"{component_note} "
            f"Mua {combo.name} là {_format_vnd(combo_price)} đồng, "
            f"rẻ hơn {_format_vnd(savings)} đồng ({percent_text}%).{availability_note}"
        )
    if savings == 0:
        return (
            f"Các món trong {combo.name} mua lẻ cũng khoảng {_format_vnd(retail_total)} đồng, "
            f"nên hiện chưa có chênh lệch giá.{availability_note}"
        )
    return (
        f"Nếu mua lẻ gồm {component_text} thì khoảng {_format_vnd(retail_total)} đồng; "
        f"giá combo hiện là {_format_vnd(combo_price)} đồng, cao hơn {_format_vnd(-savings)} đồng.{availability_note}"
    )
