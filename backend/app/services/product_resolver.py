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


def product_aliases(product: Product) -> list[str]:
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    aliases: list[str] = [product.name, product.sku]
    for key in ("aliases", "search_terms", "keywords"):
        value = metadata.get(key)
        if isinstance(value, str):
            aliases.append(value)
        elif isinstance(value, (list, tuple)):
            aliases.extend(str(item) for item in value if str(item).strip())
    return list(dict.fromkeys(alias.strip() for alias in aliases if alias and alias.strip()))


# Keep the private name for callers that imported it before the public helper
# was added.  New code should use ``product_aliases``.
_product_aliases = product_aliases


def _resolve_from_products(products: list[Product], text: str) -> Product | None:
    query = normalize_product_text(text)
    if not query:
        return None
    query_tokens = _tokens(query)
    best: tuple[float, int, Product] | None = None
    for product in products:
        score = 0.0
        for alias in product_aliases(product):
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


def resolve_product_mentions(
    db: Session,
    *,
    business_id: int,
    text: str,
    conversation_id: int | None = None,
) -> list[Product]:
    """Resolve every explicit product mention in a customer message.

    ``resolve_product`` intentionally returns one best match, which is ideal
    for short price/stock questions but loses items in messages such as
    ``"Serum và sữa rửa mặt"``.  This helper finds exact catalog aliases,
    prefers the longest alias when names overlap, and falls back to the
    single-product resolver for conversational follow-ups.
    """
    products = db.query(Product).filter(
        Product.business_id == business_id,
        Product.status == "active",
    ).order_by(Product.id.asc()).all()
    query = normalize_product_text(text)
    if not query:
        return []

    candidates: list[tuple[int, int, int, Product]] = []
    seen_candidates: set[tuple[int, int, int]] = set()
    for product in products:
        for alias in product_aliases(product):
            normalized_alias = normalize_product_text(alias)
            if len(normalized_alias) < 2:
                continue
            start = query.find(normalized_alias)
            while start >= 0:
                end = start + len(normalized_alias)
                candidate_key = (start, end, product.id)
                if candidate_key not in seen_candidates:
                    candidates.append((start, -len(normalized_alias), product.id, product))
                    seen_candidates.add(candidate_key)
                start = query.find(normalized_alias, start + 1)

            # Customers often omit descriptive suffixes ("kem chống nắng",
            # "sữa rửa mặt", or even "sữa mặt").  When the full alias is not
            # present, accept at least two meaningful catalog tokens with a
            # conservative coverage threshold.  Exact aliases above always
            # win, so a specific product such as "Serum Vitamin C Lunari" is
            # not shadowed by the generic "Serum" product.
            if query.find(normalized_alias) >= 0:
                continue
            alias_tokens = [
                token
                for token in normalized_alias.split()
                if token not in _STOP_WORDS and len(token) >= 2
            ]
            if len(alias_tokens) < 2:
                continue
            query_token_positions = [
                (match.group(0), match.start(), match.end())
                for match in re.finditer(r"\S+", query)
            ]
            matched_positions = []
            for token in alias_tokens:
                position = next(
                    (item for item in query_token_positions if item[0] == token),
                    None,
                )
                if position is not None:
                    matched_positions.append(position)
            required_matches = max(2, (len(alias_tokens) + 2) // 3)
            if len(matched_positions) < required_matches:
                continue
            start = min(item[1] for item in matched_positions)
            end = max(item[2] for item in matched_positions)
            candidate_key = (start, end, product.id)
            if candidate_key not in seen_candidates:
                candidates.append((start, -(end - start), product.id, product))
                seen_candidates.add(candidate_key)

    selected: list[Product] = []
    occupied: list[tuple[int, int]] = []
    for start, neg_length, _product_id, product in sorted(candidates, key=lambda item: (item[0], item[1], item[2])):
        end = start - neg_length
        if product in selected:
            continue
        if any(start < other_end and end > other_start for other_start, other_end in occupied):
            continue
        selected.append(product)
        occupied.append((start, end))

    if selected:
        return selected
    fallback = resolve_product(
        db,
        business_id=business_id,
        text=text,
        conversation_id=conversation_id,
    )
    return [fallback] if fallback is not None else []


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
