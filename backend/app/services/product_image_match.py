"""Small tenant-scoped helpers for matching a customer photo to catalog items."""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.models.sales import Product
from app.services.product_resolver import normalize_product_text, product_aliases


@dataclass(frozen=True)
class ProductImageCandidate:
    product: Product
    score: float


def product_image_url(product: Product) -> str | None:
    metadata = getattr(product, "metadata_", None)
    if not isinstance(metadata, dict):
        metadata = getattr(product, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    for key in ("image_url", "imageUrl", "photo_url", "photoUrl", "thumbnail_url", "thumbnailUrl"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    images = metadata.get("images")
    if isinstance(images, list):
        for value in images:
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                url = value.get("url") or value.get("image_url")
                if isinstance(url, str) and url.strip():
                    return url.strip()
    return None


def _catalog_text(product: Product) -> str:
    metadata = getattr(product, "metadata_", None)
    if not isinstance(metadata, dict):
        metadata = getattr(product, "metadata", None)
    terms = [str(getattr(product, name, "") or "") for name in ("sku", "name", "description")]
    terms.extend(product_aliases(product))
    if isinstance(metadata, dict):
        for key in ("image_description", "visual_description", "category", "keywords", "aliases", "search_terms"):
            value = metadata.get(key)
            if isinstance(value, str):
                terms.append(value)
            elif isinstance(value, (list, tuple)):
                terms.extend(str(item) for item in value)
        attributes = metadata.get("attributes")
        if isinstance(attributes, dict):
            terms.extend(str(value) for value in attributes.values())
    return " ".join(terms)


def rank_product_image_candidates(
    products: list[Product],
    visual_description: str,
    *,
    limit: int = 5,
) -> list[ProductImageCandidate]:
    """Use visible product attributes to shortlist; the vision model verifies photos."""
    query = normalize_product_text(visual_description)
    stop = {"anh", "hinh", "san", "pham", "mot", "cua", "voi", "dang", "mau", "loai", "shop", "khach"}
    query_terms = {term for term in query.split() if len(term) > 1 and term not in stop}
    if not query_terms:
        return []

    ranked: list[ProductImageCandidate] = []
    for product in products:
        catalog = normalize_product_text(_catalog_text(product))
        catalog_terms = set(catalog.split())
        overlap = query_terms & catalog_terms
        if not overlap:
            continue
        # Query coverage dominates, so long product descriptions do not bury a
        # strong match. Ties are preserved for the visual model to disambiguate.
        score = len(overlap) / len(query_terms) + 0.15 * len(overlap) / max(len(catalog_terms), 1)
        ranked.append(ProductImageCandidate(product=product, score=score))
    ranked.sort(key=lambda item: (-item.score, int(getattr(item.product, "id", 0) or 0)))
    return ranked[:max(1, min(int(limit), 5))]


def parse_product_match(value: str, allowed_skus: set[str]) -> tuple[str | None, float]:
    """Accept only a candidate SKU returned in the expected JSON shape."""
    import json

    raw = str(value or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None, 0.0
    if not isinstance(payload, dict):
        return None, 0.0
    sku = str(payload.get("product_sku") or "").strip()
    try:
        confidence = float(payload.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    if sku not in allowed_skus or not 0 <= confidence <= 1:
        return None, 0.0
    return sku, confidence
