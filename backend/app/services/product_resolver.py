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

_CATALOG_QUERY_FILLERS = {
    "anh", "bao", "ban", "ben", "chi", "dang", "day", "gia", "giup", "hang",
    "hien", "hoac", "khac", "kiem", "loai", "moi", "nao", "nhau", "nhieu",
    "ma", "san", "sanh", "shop", "so", "tai", "theo", "toi", "tra", "tu",
    "va", "voi", "xem", "xin", "co", "con", "cho", "cua", "het", "khong",
    "la", "mua", "pham", "thanh", "thi", "tien", "tong", "muon", "vay",
}


def normalize_product_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    normalized = normalized.replace("đ", "d")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _dimension_tokens(value: object) -> set[str]:
    """Keep numeric parts of explicit size dimensions such as 70/90-17."""
    tokens: set[str] = set()
    for match in re.finditer(
        r"(?<!\d)(\d{1,3}(?:[.,]\d{1,2})?)\s*/\s*"
        r"(\d{1,3}(?:[.,]\d{1,2})?)\s*-\s*(\d{2,3})(?!\d)",
        str(value or ""),
    ):
        for component in match.groups():
            tokens.update(normalize_product_text(component).split())
    return tokens


def _dimension_keys(value: object) -> set[str]:
    """Extract complete numeric dimensions so similar sizes do not collapse."""
    keys = set()
    for match in re.finditer(
        r"(?<!\d)(\d{1,3}(?:[.,]\d{1,2})?)\s*/\s*"
        r"(\d{1,3}(?:[.,]\d{1,2})?)\s*-\s*(\d{2,3})(?!\d)",
        str(value or ""),
    ):
        parts = [re.sub(r"\s+", "", part.replace(",", ".")) for part in match.groups()]
        keys.add(f"{parts[0]}/{parts[1]}-{parts[2]}")
    return keys


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_product_text(value).split()
        if len(token) >= 2 and token not in _STOP_WORDS and not token.isdigit()
    }


def _name_aliases(product: Product) -> list[str]:
    return list(dict.fromkeys([product.name, re.sub(r"^\[DEMO\]\s*", "", product.name, flags=re.I)]))


def product_aliases(product: Product) -> list[str]:
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    aliases: list[str] = [*_name_aliases(product), product.sku]
    for key in ("aliases", "search_terms", "keywords"):
        value = metadata.get(key)
        if isinstance(value, str):
            aliases.append(value)
        elif isinstance(value, (list, tuple)):
            aliases.extend(str(item) for item in value if str(item).strip())
    return list(dict.fromkeys(alias.strip() for alias in aliases if alias and alias.strip()))


def product_identity_aliases(product: Product) -> list[str]:
    """Names/SKUs and curated aliases; search keywords are weaker evidence."""
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    aliases = metadata.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    return list(dict.fromkeys(
        value.strip()
        for value in (*_name_aliases(product), product.sku, *aliases)
        if isinstance(value, str) and value.strip()
    ))


def find_explicit_product_mentions(products: list[Product], text: str) -> list[Product]:
    """Return catalog products explicitly identified by a query, including variants.

    Exact SKU/name aliases win. For shortened names, distinctive tokens are
    matched against the current tenant catalog; common catalog words are
    discounted so a request such as two tire sizes can resolve both sizes
    without confusing them with every product sharing "vehicle" or "size".
    This helper is intentionally conservative and does not use embeddings or
    return a nearest-neighbour guess.
    """
    normalized_query = normalize_product_text(text)
    if not normalized_query:
        return []
    padded_query = f" {normalized_query} "

    exact_matches: dict[int, Product] = {}
    for product in products:
        for alias in product_identity_aliases(product):
            normalized_alias = normalize_product_text(alias)
            if normalized_alias and f" {normalized_alias} " in padded_query:
                exact_matches[int(product.id)] = product
                break
    # Keep exact hits, but do not return yet: a comparison can contain one
    # exact product name and a second shortened variant (for example
    # "lốp 70/90-17 và 80/90-17"). The distinctive-token pass below can find
    # that second item without broadening ordinary single-item lookups.

    requested_dimensions = _dimension_keys(text)
    if requested_dimensions:
        dimension_matches = []
        for product in products:
            metadata = product.metadata_ if isinstance(getattr(product, "metadata_", None), dict) else {}
            attributes = metadata.get("attributes") if isinstance(metadata.get("attributes"), dict) else {}
            sources = [product.name, *product_aliases(product)]
            for key, raw in attributes.items():
                if str(key).casefold() in {"size", "sizes", "tire_size", "tyre_size", "kich_thuoc"}:
                    sources.extend(raw if isinstance(raw, (list, tuple, set)) else [raw])
            if any(_dimension_keys(source) & requested_dimensions for source in sources):
                dimension_matches.append(product)
        if dimension_matches:
            return sorted(dimension_matches, key=lambda product: int(product.id or 0))
        return []

    query_tokens = {
        token for token in normalized_query.split()
        if len(token) >= 2 and token not in _STOP_WORDS and token not in _CATALOG_QUERY_FILLERS
    }
    query_tokens.update(_dimension_tokens(text))
    if not query_tokens or not products:
        return []

    product_tokens: dict[int, set[str]] = {}
    token_frequency: dict[str, int] = {}
    by_id = {int(product.id): product for product in products}
    for product in products:
        tokens = {
            token for token in normalize_product_text(product.name).split()
            if len(token) >= 2 and token not in _STOP_WORDS and token not in _CATALOG_QUERY_FILLERS
        }
        dimension_sources = [product.name, *product_aliases(product)]
        metadata = product.metadata_ if isinstance(getattr(product, "metadata_", None), dict) else {}
        attributes = metadata.get("attributes") if isinstance(metadata.get("attributes"), dict) else {}
        dimension_sources.extend(
            str(value)
            for key, raw in attributes.items()
            if str(key).casefold() in {"size", "sizes", "tire_size", "tyre_size", "kich_thuoc"}
            for value in (raw if isinstance(raw, (list, tuple, set)) else [raw])
            if str(value or "").strip()
        )
        for source in dimension_sources:
            tokens.update(_dimension_tokens(source))
        product_tokens[int(product.id)] = tokens
        for token in tokens:
            token_frequency[token] = token_frequency.get(token, 0) + 1

    # Prefer words that distinguish a catalog entry from other entries. This
    # retains dimensions, model names and left/right variants while reducing
    # generic category matches.
    common_cutoff = max(5, int(len(products) * 0.35 + 0.999))
    distinctive = {
        product_id: {
            token for token in tokens
            if token_frequency.get(token, 0) < common_cutoff
        }
        for product_id, tokens in product_tokens.items()
    }
    overlaps = {
        product_id: tokens & query_tokens
        for product_id, tokens in distinctive.items()
    }
    overlaps = {product_id: tokens for product_id, tokens in overlaps.items() if tokens}
    if not overlaps:
        return []

    rare_query_tokens = {
        token for token in query_tokens if token_frequency.get(token, 0) == 1
    }
    rare_matches = {
        product_id for product_id, tokens in overlaps.items()
        if tokens & rare_query_tokens
    }

    asks_for_multiple = bool(re.search(
        r"\b(?:va|voi|cung|and|or|with|together|both|vs|versus|so sanh|khac nhau|khac gi|compare|comparison)\b",
        normalized_query,
    ))
    if exact_matches:
        if len(exact_matches) == 1 and asks_for_multiple and rare_matches:
            exact_matches.update({
                product_id: by_id[product_id]
                for product_id in rare_matches
                if product_id in by_id
            })
        return sorted(exact_matches.values(), key=lambda product: int(product.id or 0))

    if asks_for_multiple:
        # For a bundle request such as "air filter and spark plug", a strict
        # max-score tie discarded the second category because its noun appears
        # in fewer catalog names. Keep every tenant catalog item matched by a
        # distinctive requested token; downstream fitment filters still apply.
        matched_ids = {
            product_id
            for product_id, tokens in overlaps.items()
            if tokens
        }
        if matched_ids:
            return [by_id[product_id] for product_id in sorted(matched_ids)]

    if rare_matches:
        return [by_id[product_id] for product_id in sorted(rare_matches)]

    best_score = max(len(tokens) for tokens in overlaps.values())
    # A tie is useful for broad, explicit category requests (for example all
    # matching NGK plugs); a weaker partial match is not silently appended.
    return [
        by_id[product_id]
        for product_id, tokens in sorted(overlaps.items())
        if len(tokens) == best_score
    ]


def _ranked_identity_matches(
    products: list[Product],
    text: str,
    *,
    variant_tokens: set[str] | None = None,
) -> list[Product]:
    query_tokens = normalize_product_text(text).split()
    if not query_tokens:
        return []

    scores: dict[int, int] = {}
    for product in products:
        identity_aliases = product_identity_aliases(product)
        if variant_tokens:
            identity_text = " " + " ".join(
                normalize_product_text(alias) for alias in identity_aliases
            ) + " "
            if not all(
                f" {normalize_product_text(token)} " in identity_text
                for token in variant_tokens
            ):
                continue
        best_match = 0
        for alias in identity_aliases:
            alias_tokens = normalize_product_text(alias).split()
            if not alias_tokens:
                continue
            for start, token in enumerate(query_tokens):
                if token != alias_tokens[0]:
                    continue
                matched = 0
                while (
                    matched < len(alias_tokens)
                    and start + matched < len(query_tokens)
                    and alias_tokens[matched] == query_tokens[start + matched]
                ):
                    matched += 1
                best_match = max(best_match, matched)
        if best_match:
            scores[int(product.id)] = best_match

    if not scores:
        return []
    best_score = max(scores.values())
    return [product for product in products if scores.get(int(product.id)) == best_score]


def find_ambiguous_product_matches(
    db: Session,
    *,
    business_id: int,
    text: str,
    variant_tokens: set[str] | None = None,
) -> list[Product]:
    """Return tied best catalog identities when a name/variant is ambiguous."""
    products = db.query(Product).filter(
        Product.business_id == business_id,
        Product.status == "active",
    ).order_by(Product.id.asc()).all()
    matches = _ranked_identity_matches(products, text, variant_tokens=variant_tokens)
    return matches if len(matches) > 1 else []


def resolve_prior_product_mention(
    db: Session,
    *,
    business_id: int,
    conversation_id: int,
    current_text: str,
    products: list[Product] | None = None,
) -> Product | None:
    """Resolve the latest unambiguous product in the active chat turn.

    A unique product named in the immediately preceding bot/staff reply can be
    used for "cái đó" follow-ups. Multi-product replies stay ambiguous; stale
    customer references are not carried across a newer unrelated question.
    """
    products = products or db.query(Product).filter(
        Product.business_id == business_id,
        Product.status == "active",
    ).order_by(Product.id.asc()).all()
    current_normalized = normalize_product_text(current_text)
    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.content.isnot(None),
    ).order_by(Message.id.desc()).limit(12).all()
    for message in messages:
        previous_text = str(getattr(message, "content", None) or "").strip()
        if not previous_text or normalize_product_text(previous_text) == current_normalized:
            continue
        direction = getattr(message, "direction", "inbound")
        sender_type = getattr(message, "sender_type", "customer")
        if direction == "outbound" and sender_type in {"bot", "staff"}:
            folded_text = f" {normalize_product_text(previous_text)} "
            exact_matches = {
                int(product.id): product
                for product in products
                if any(
                    len(normalize_product_text(alias)) >= 3
                    and f" {normalize_product_text(alias)} " in folded_text
                    for alias in product_identity_aliases(product)
                )
            }
            if len(exact_matches) > 1:
                # A list of products needs a clarifying question, not an arbitrary pick.
                return None
            if exact_matches:
                return next(iter(exact_matches.values()))
            continue
        if direction == "inbound" and sender_type == "customer":
            matches = _ranked_identity_matches(products, previous_text)
            if len(matches) > 1:
                return None
            if matches:
                return matches[0]
            # Do not reuse an entity from before the customer's latest other topic.
            return None
    return None


def product_display_name(product: Product, language: str = "vi") -> str:
    """Use a curated localized label without changing the catalog's canonical name."""
    if language == "en":
        raw_metadata = getattr(product, "metadata_", None)
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        names = metadata.get("display_names") if isinstance(metadata.get("display_names"), dict) else {}
        translated = names.get("en") or metadata.get("display_name_en")
        if isinstance(translated, str) and translated.strip():
            return translated.strip()
    return product.name


# Keep the private name for callers that imported it before the public helper
# was added.  New code should use ``product_aliases``.
_product_aliases = product_aliases


def _resolve_from_products(products: list[Product], text: str) -> Product | None:
    query = normalize_product_text(text)
    if not query:
        return None
    query_tokens = _tokens(query)
    scored: list[tuple[float, Product]] = []
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
        scored.append((score, product))

    if not scored:
        return None
    best_score = max(score for score, _product in scored)
    if best_score < 0.75:
        return None
    best_matches = [product for score, product in scored if score == best_score]
    # A lexical tie between variants is ambiguity, not permission to choose the
    # lowest database ID. Ask the customer to identify the exact model/SKU.
    if len(best_matches) != 1:
        return None
    return best_matches[0]


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

    identity_candidates: list[tuple[int, int, int, Product]] = []
    fallback_candidates: list[tuple[int, int, int, Product]] = []
    seen_candidates: set[tuple[int, int, int]] = set()
    seen_identity_candidates: set[tuple[int, int, int]] = set()
    for product in products:
        identity_aliases = set(product_identity_aliases(product))
        for alias in product_aliases(product):
            target_candidates = identity_candidates if alias in identity_aliases else fallback_candidates
            normalized_alias = normalize_product_text(alias)
            if len(normalized_alias) < 2:
                continue
            start = query.find(normalized_alias)
            while start >= 0:
                end = start + len(normalized_alias)
                candidate_key = (start, end, product.id)
                seen = seen_identity_candidates if target_candidates is identity_candidates else seen_candidates
                if candidate_key not in seen:
                    target_candidates.append((start, -len(normalized_alias), product.id, product))
                    seen.add(candidate_key)
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
                if token not in _STOP_WORDS and len(token) >= 2 and not token.isdigit()
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
                fallback_candidates.append((start, -(end - start), product.id, product))
                seen_candidates.add(candidate_key)

    candidates = identity_candidates or fallback_candidates
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

    return resolve_prior_product_mention(
        db,
        business_id=business_id,
        conversation_id=conversation_id,
        current_text=text,
        products=products,
    )
