"""Resolve customer product mentions to tenant-owned Product rows."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.models.message import Message
from app.models.sales import Product


_STOP_WORDS = {
    "bao", "bay", "co", "cai", "cho", "cua", "gia", "gi", "het", "khong",
    "la", "mua", "nhieu", "san", "pham", "thanh", "thi", "tien", "toi",
    "tong", "muon", "vay", "voi", "so", "luong", "bo", "bo", "don",
}


def normalize_product_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    normalized = normalized.replace("đ", "d")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_product_text(value).split()
        if len(token) >= 2 and token not in _STOP_WORDS and not token.isdigit()
    }


def _product_aliases(product: Product) -> list[str]:
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    aliases: list[str] = [product.name, product.sku]
    for key in ("aliases", "search_terms", "keywords"):
        value = metadata.get(key)
        if isinstance(value, str):
            aliases.append(value)
        elif isinstance(value, (list, tuple)):
            aliases.extend(str(item) for item in value if str(item).strip())
    return list(dict.fromkeys(alias.strip() for alias in aliases if alias and alias.strip()))


def _resolve_from_products(products: list[Product], text: str) -> Product | None:
    query = normalize_product_text(text)
    if not query:
        return None
    query_tokens = _tokens(query)
    best: tuple[float, int, Product] | None = None
    for product in products:
        score = 0.0
        for alias in _product_aliases(product):
            normalized_alias = normalize_product_text(alias)
            if not normalized_alias:
                continue
            if normalized_alias == query:
                score = max(score, 2.0)
                continue
            if normalized_alias in query:
                score = max(score, 1.6 + min(len(normalized_alias.split()) * 0.03, 0.2))
                continue
            alias_tokens = _tokens(normalized_alias)
            if not alias_tokens or not query_tokens:
                continue
            coverage = len(alias_tokens & query_tokens) / len(alias_tokens)
            ratio = SequenceMatcher(None, normalized_alias, query).ratio()
            score = max(score, coverage * 1.1 + ratio * 0.25)
        if best is None or score > best[0] or (score == best[0] and product.id < best[1]):
            best = (score, product.id, product)

    if best is None or best[0] < 0.75:
        return None
    return best[2]


def resolve_product(
    db: Session,
    *,
    business_id: int,
    text: str,
    conversation_id: int | None = None,
) -> Product | None:
    products = db.query(Product).filter(
        Product.business_id == business_id,
        Product.status == "active",
    ).order_by(Product.id.asc()).all()
    product = _resolve_from_products(products, text)
    if product is not None or conversation_id is None:
        return product

    # Short follow-ups such as “giá của 6 bộ đó” inherit the last explicit
    # product mention from the customer's own messages, not an arbitrary
    # product from the bot's catalog list.
    previous_messages = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.direction == "inbound",
        Message.content.isnot(None),
    ).order_by(Message.id.desc()).limit(10).all()
    for message in previous_messages:
        product = _resolve_from_products(products, message.content or "")
        if product is not None:
            return product
    return None
