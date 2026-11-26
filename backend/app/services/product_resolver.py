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
    normalized = " ".join(normalized.split())
    # Common customer typos should resolve consistently in exact lookup,
    # fitment filtering, and recommendation matching.
    return re.sub(r"\bwave\s+an(?:f|ph)a\b", "wave alpha", normalized)


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
    # Purchase scaffolding is not product identity (đặt vs đất after folding).
    # Remove only a leading purchase command; keep the same word inside names.
    # A bare literal name starting with “đất” is not a purchase command.
    if not re.match(r"^\s*đất\b", text, re.I):
        normalized_query = re.sub(
            r"^(?:(?:ok|cho|toi|minh|em|anh|chi|ban|tao|vay|muon|can|xin|hay)\s+)*"
            r"(?:dat(?: hang)?|mua|lay|chot(?: don)?)\s+"
            r"(?:\d+\s+)?(?:(?:don|cai|chai|lo|hop|chiec|san pham)\s+)?",
            "", normalized_query,
        )
    if not normalized_query:
        return []
    exact_spans = []
    for product in products:
        for alias in product_identity_aliases(product):
            normalized_alias = normalize_product_text(alias)
            if normalized_alias:
                exact_spans.extend(
                    (match.start(), match.end(), product)
                    for match in re.finditer(
                        r"(?<!\w)" + re.escape(normalized_alias) + r"(?!\w)", normalized_query,
                    )
                )
    # A short product name inside another complete name is not an additional
    # cart item. Keep it only when it also occurs separately in this message.
    exact_matches: dict[int, Product] = {
        int(product.id): product for start, end, product in exact_spans
        if not any(
            other.id != product.id and outer_start <= start and end <= outer_end
            and (outer_start < start or end < outer_end)
            for outer_start, outer_end, other in exact_spans
        )
    }
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
    # A new named subject must never borrow an unrelated historical item.
    # Variant-only replies can still select from the preceding choices.
    current_tokens = set(current_normalized.split())
    variant_words = {"tieu", "chuan", "nho", "gon", "nang", "cao", "bo", "doi", "ban", "mau"}
    matched_identity_tokens = set()
    for product in products:
        identity_tokens = set(normalize_product_text(product.name).split()) - _STOP_WORDS - _CATALOG_QUERY_FILLERS - {"dat", "lay", "chot", "hang", "luon"}
        matched_identity_tokens.update(current_tokens & identity_tokens)
    if matched_identity_tokens - variant_words:
        if not re.search(r"\b(?:do|nay|ay|tren|vua)\b", current_normalized):
            return None
        # A named category plus a reference can narrow history, but can never
        # borrow an item from another category just because it was mentioned.
        products = [p for p in products if (matched_identity_tokens - variant_words)
                    <= set(normalize_product_text(p.name).split())]
        if not products:
            return None
    # History is reserved for references, variant choices and short follow-ups.
    if not (matched_identity_tokens or _is_unidentified_product_detail_followup(current_text)
            or re.search(r"\b(?:do|nay|ay|tren|vua|them|dat hang|dat|lay|chot|mua\s+(?:\d+|mot)\s+(?:cai|chai|san pham)|cho\s+(?:toi|minh|em)\s+\d+\s+cai)\b", current_normalized)
            or re.fullmatch(r"(?:con hang khong|con bao nhieu|gia bao nhieu)(?: a| nhi| vay)?[?.!]*", current_normalized)):
        return None
    products_by_id = {
        int(product.id): product
        for product in products
        if getattr(product, "id", None) is not None
    }
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
            # Image matching and catalog replies persist the exact tenant-owned
            # product ID. Prefer that provenance over re-parsing a display name.
            metadata = getattr(message, "metadata_", None)
            crm_product = metadata.get("crm_product") if isinstance(metadata, dict) else None
            product_id = crm_product.get("id") if isinstance(crm_product, dict) else None
            try:
                exact_product = products_by_id.get(int(product_id)) if product_id is not None else None
            except (TypeError, ValueError):
                exact_product = None
            if exact_product is not None:
                return exact_product
            dialogue = metadata.get("catalog_dialogue") if isinstance(metadata, dict) else None
            shortlist = dialogue.get("shortlist", []) if isinstance(dialogue, dict) else []
            if len(shortlist) == 1 and shortlist[0] in products_by_id:
                return products_by_id[shortlist[0]]
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
                # A customer's variant answer may identify one item from
                # the immediately preceding choices ("lấy bản tiêu chuẩn").
                # Require at least two identity tokens and one unique match.
                selection_tokens = set(current_normalized.split()) - _STOP_WORDS - _CATALOG_QUERY_FILLERS - {
                    "minh", "em", "chon", "lay", "dat", "nhe", "nha", "a", "nua",
                }
                matches = [product for product in exact_matches.values()
                    if len(selection_tokens & set(normalize_product_text(product.name).split())) >= 2]
                if len(matches) == 1:
                    return matches[0]
                # A list alone is never permission to choose its first item.
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
            if _is_unidentified_product_detail_followup(previous_text):
                # A detail/confirmation follow-up without a new item name is
                # still about the last uniquely proposed product. Don't let a
                # prior generic fallback reply sever that short context chain.
                continue
            # Do not reuse an entity from before the customer's latest other topic.
            return None
    return None


def _is_unidentified_product_detail_followup(text: str) -> bool:
    normalized = normalize_product_text(text)
    if not normalized:
        return False
    cues = (
        "xac nhan dung mau roi", "xac nhan dung mau", "dung mau roi", "dung mau",
        "xac nhan dung roi", "xac nhan", "dung roi", "chinh xac",
        "chi tiet san pham", "chi tiet", "mo ta san pham", "mo ta",
        "thong tin san pham", "product details", "product description", "details",
    )
    remaining = normalized
    matched = False
    for cue in sorted(cues, key=len, reverse=True):
        if cue in remaining:
            remaining = remaining.replace(cue, " ")
            matched = True
    if not matched:
        return False
    conversational_fillers = {
        "a", "ban", "cho", "do", "i", "la", "me", "minh", "nhe", "please",
        "muon", "roi", "san", "pham", "toi", "want", "xem", "yeah", "yes", "you",
    }
    return not [token for token in remaining.split() if token not in conversational_fillers]


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


def product_family(product):
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    for container in (metadata.get("product_profile"), metadata.get("attributes"), metadata):
        if isinstance(container, dict):
            category = container.get("category")
            if isinstance(category, list):
                category = next((v for v in category if isinstance(v, str) and v.strip()), None)
            if isinstance(category, str) and category.strip():
                return category.strip()
    name = re.split(r"\s+[–—-]\s+", product.name)[0]
    return re.sub(r"\s+\d+(?:[.,]\d+)?\s*(?:ml|g|kg|l)\s*$", "", name, flags=re.I).strip()


def _reference_only(text):
    query = normalize_product_text(text)
    # A counted purchase with no product noun is a reference too. Never score
    # conversational words such as đặt against catalog names (đất sét).
    if re.search(r"\b(?:dat|mua|lay|chot)\b", query) and re.fullmatch(
        r"(?:(?:ok|cho|toi|minh|em|anh|chi|ban|tao|vay|muon|xin|hay|dat|hang|mua|lay|chot|mot|[0-9]+|cai|chai|lo|hop|chiec|bo|san pham|mon|loai|di|nhe|nha|voi|luon|a)\s*)+", query):
        return True
    return bool(re.fullmatch(r"(?:(?:cho|toi|minh|em|anh|chi|ban|tao|ok|vay|muon|xin|hay|dat|hang|mua|lay|chot|mot|[0-9]+|cai|san pham|mon|loai|di|nhe|nha|voi)\s+)*(?:no|do|nay|ay)(?:\s+(?:di|nhe|nha|voi|luon|a))*", query))


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


def _variant_only_selection(products, text):
    tokens = set(normalize_product_text(text).split())
    variants = {"tieu", "chuan", "nho", "gon", "nang", "cao", "bo", "doi", "ban", "mau"}
    identity = set().union(*(set(normalize_product_text(p.name).split()) - _STOP_WORDS - _CATALOG_QUERY_FILLERS - {"dat", "lay", "chot", "hang", "luon"} for p in products))
    matched = tokens & identity
    return bool(matched & variants) and not (matched - variants)


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
    if _reference_only(text):
        prior = resolve_prior_product_mention(db, business_id=business_id,
            conversation_id=conversation_id, current_text=text, products=products) if conversation_id else None
        return [prior] if prior else []
    if _variant_only_selection(products, text):
        prior = resolve_prior_product_mention(db, business_id=business_id,
            conversation_id=conversation_id, current_text=text, products=products) if conversation_id else None
        return [prior] if prior else []
    query = normalize_product_text(text)
    if not query:
        return []

    # Share the conservative resolver used by catalog lookup. The older
    # token-span fallback could mistake common words ("sữa", "tiêu chuẩn")
    # for product identity and select the first database row on a tie.
    explicit = find_explicit_product_mentions(products, text)
    # In conversational Vietnamese, "đặt với nha/nhé" is a polite purchase
    # request, not a conjunction between multiple products. Do not let this
    # filler prevent the recent, uniquely mentioned product from resolving.
    multiple_query = re.sub(
        r"\b(dat|mua|lay|chot)\s+voi(?:\s+(?:nha|nhe|a|di))?\b",
        r"\1",
        query,
    )
    asks_for_multiple = bool(re.search(
        r"\b(?:va|voi|cung|and|or|with|together|both|vs|versus|so sanh|khac nhau|khac gi|compare|comparison)\b",
        multiple_query,
    ))
    if asks_for_multiple:
        return explicit

    padded_query = f" {query} "
    exact_ids = {
        int(product.id)
        for product in products
        if any(
            (normalized_alias := normalize_product_text(alias))
            and f" {normalized_alias} " in padded_query
            for alias in product_identity_aliases(product)
        )
    }
    if len(exact_ids) > 1:
        return explicit
    if len(explicit) == 1:
        return explicit
    if len(explicit) > 1:
        if len({product_family(p) for p in explicit}) == 1 and not exact_ids:
            prior = resolve_prior_product_mention(db, business_id=business_id,
                conversation_id=conversation_id, current_text="đặt nó", products=products) if conversation_id else None
            return [prior] if prior is not None and prior in explicit else []
        # Several shortened variants with the same evidence are ambiguous.
        # Only the single-product scorer may break that tie.
        fallback = _resolve_from_products(products, text)
        return [fallback] if fallback is not None else []

    fallback = _resolve_from_products(products, text)
    if fallback is not None:
        return [fallback]
    if conversation_id is None:
        return []
    prior = resolve_prior_product_mention(
        db,
        business_id=business_id,
        conversation_id=conversation_id,
        current_text=text,
        products=products,
    )
    return [prior] if prior is not None else []


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
    if _reference_only(text):
        return resolve_prior_product_mention(db, business_id=business_id,
            conversation_id=conversation_id, current_text=text, products=products) if conversation_id else None
    if _variant_only_selection(products, text):
        return resolve_prior_product_mention(db, business_id=business_id,
            conversation_id=conversation_id, current_text=text, products=products) if conversation_id else None
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
