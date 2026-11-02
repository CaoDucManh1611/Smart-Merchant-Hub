"""Tenant-safe catalog predicates applied inside retrieval SQL before LIMIT."""
from __future__ import annotations

import unicodedata
from collections.abc import Mapping
import re
from typing import Any


_OBJECT_TYPES = {"product", "service", "rental"}
_CHUNK_ID_EXPRESSIONS = {"dc.id", "sc.id"}
_CHUNK_CONTENT_EXPRESSIONS = {"dc.content", "sc.content"}
_ATTRIBUTE_KEY_ALIASES = {
    "size": ("size", "sizes", "kich_thuoc", "kich thuoc", "kích_thước", "kích thước"),
    "volume": ("volume", "capacity", "dung_tich", "dung tích", "thể_tích", "thể tích"),
    "color": (
        "color", "colors", "colour", "colours", "mau", "mau_sac", "mau sac",
        "màu", "màu_sắc", "màu sắc",
    ),
}
_COLOR_VALUE_ALIASES = {
    "red": ("red", "đỏ", "do"),
    "pink": ("pink", "hồng", "hong", "rose"),
    "blue": ("blue", "xanh dương", "xanh duong", "xanh lam", "navy"),
    "green": ("green", "xanh lá", "xanh la", "xanh lục", "xanh luc"),
    "black": ("black", "đen", "den"),
    "white": ("white", "trắng", "trang", "ivory"),
    "yellow": ("yellow", "vàng", "vang"),
    "purple": ("purple", "tím", "tim", "violet"),
    "brown": ("brown", "nâu", "nau"),
    "gray": ("gray", "grey", "xám", "xam"),
}


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return " ".join(text.split())


def extract_query_hard_filters(query: str, *, object_type: str | None = None) -> dict[str, Any]:
    """Extract explicitly labelled size, volume, and color constraints."""
    text = unicodedata.normalize("NFKC", str(query or "")).casefold()
    filters: dict[str, Any] = {}
    if object_type is not None:
        kind = _normalize(object_type)
        if kind not in _OBJECT_TYPES:
            raise ValueError("object_type must be product, service, or rental")
        filters["object_type"] = kind

    size = re.search(
        r"\b(?:size|kích thước|kich thuoc)\s*(?:là|la|:)?\s*"
        r"(?P<value>xxxs|xxs|xxl|xxxl|xs|xl|s|m|l|"
        r"[a-z0-9]+(?:[./-][a-z0-9]+)*"
        r"(?:\s*(?:millilit(?:er|re)s?|ml|cl|dl|lít|lit(?:er|re)?s?|cm|mm|ah|v|inch|in))?)\b",
        text,
    )
    if size:
        value = _normalize(size.group("value"))
        key = "volume" if re.search(
            r"\b(?:millilit(?:er|re)s?|ml|cl|dl|lít|lit(?:er|re)?s?)\b", value,
        ) else "size"
        filters.setdefault("required_attributes", {})[key] = value

    color = re.search(
        r"\b(?:màu|mau|color|colour)\s+(xanh\s+(?:dương|duong|lam|lá|la|lục|luc)|xanh|"
        r"dark\s+blue|light\s+blue|red|đỏ|do|pink|hồng|hong|blue|green|black|đen|den|"
        r"white|trắng|trang|yellow|vàng|vang|purple|tím|tim|brown|nâu|nau|gray|grey|xám|xam)\b",
        text,
    )
    if color:
        value = _normalize(color.group(1))
        canonical = next((key for key, aliases in _COLOR_VALUE_ALIASES.items() if value in {_normalize(alias) for alias in aliases}), None)
        filters.setdefault("required_attributes", {})["color"] = canonical or value
    return filters


def _attribute_key_values(key: str, value: Any) -> tuple[list[str], list[str]]:
    normalized_key = _normalize(key).replace(" ", "_")
    normalized_value = _normalize(value)
    key_aliases = _ATTRIBUTE_KEY_ALIASES.get(normalized_key, (normalized_key,))
    value_aliases = (normalized_value,)
    if normalized_key == "color":
        value_aliases = next(
            (aliases for canonical, aliases in _COLOR_VALUE_ALIASES.items() if normalized_value == canonical),
            value_aliases,
        )
    return [_normalize(alias) for alias in key_aliases], [_normalize(alias) for alias in value_aliases]


def attribute_key_aliases(key: str) -> tuple[str, ...]:
    normalized_key = _normalize(key)
    return tuple(_normalize(alias) for alias in _ATTRIBUTE_KEY_ALIASES.get(normalized_key, (normalized_key,)))


def attribute_value_aliases(key: str, value: Any) -> tuple[str, ...]:
    return tuple(_attribute_key_values(key, value)[1])


def catalog_hard_filter_sql(
    hard_filters: Mapping[str, Any] | None,
    *,
    chunk_id_expression: str,
    chunk_content_expression: str | None = None,
    dialect_name: str = "postgresql",
) -> tuple[str, dict[str, Any]]:
    """Return an AND EXISTS predicate plus bound params; reject unknown filters."""
    if not hard_filters:
        return "", {}
    if chunk_id_expression not in _CHUNK_ID_EXPRESSIONS:
        raise ValueError("unsupported chunk alias")
    if chunk_content_expression is not None and chunk_content_expression not in _CHUNK_CONTENT_EXPRESSIONS:
        raise ValueError("unsupported chunk content alias")
    allowed = {"object_type", "sku", "required_attributes"}
    unknown = set(hard_filters) - allowed
    if unknown:
        raise ValueError(f"unsupported hard filters: {sorted(unknown)}")
    if not any((
        hard_filters.get("object_type") is not None,
        hard_filters.get("sku") is not None,
        bool(hard_filters.get("required_attributes")),
    )):
        return "", {}

    params: dict[str, Any] = {}
    conditions = ["rce.business_id = :business_id"]
    object_type = hard_filters.get("object_type")
    if object_type is not None:
        object_type = _normalize(object_type)
        if object_type not in _OBJECT_TYPES:
            raise ValueError("object_type must be product, service, or rental")
        conditions.append("rce.object_type = :hard_filter_object_type")
        params["hard_filter_object_type"] = object_type

    normalized_skus: list[str] = []
    sku = hard_filters.get("sku")
    if sku is not None:
        sku_values = sku if isinstance(sku, (list, tuple, set, frozenset)) else [sku]
        normalized_skus = sorted({_normalize(value) for value in sku_values})
        if not normalized_skus or any(not value for value in normalized_skus):
            raise ValueError("sku hard filter cannot be empty")
        keys = []
        for index, value in enumerate(normalized_skus):
            key = f"hard_filter_sku_{index}"
            keys.append(f":{key}")
            params[key] = value[:120]
        conditions.append(f"rce.sku_norm IN ({', '.join(keys)})")

    attrs = hard_filters.get("required_attributes") or {}
    if not isinstance(attrs, Mapping):
        raise ValueError("required_attributes must be a key/value mapping")
    for index, (key, value) in enumerate(attrs.items()):
        key_values, value_values = _attribute_key_values(key, value)
        if not key_values or not value_values:
            raise ValueError("required attribute keys and values cannot be empty")
        key_params = []
        for alias_index, alias in enumerate(key_values):
            param = f"hard_filter_attr_key_{index}_{alias_index}"
            key_params.append(f":{param}")
            params[param] = alias[:100]
        value_params = []
        for alias_index, alias in enumerate(value_values):
            param = f"hard_filter_attr_value_{index}_{alias_index}"
            value_params.append(f":{param}")
            params[param] = alias[:255]
        conditions.append(
            "EXISTS (SELECT 1 FROM recommendation_catalog_attributes rca "
            "WHERE rca.catalog_entry_id = rce.id "
            f"AND rca.key_norm IN ({', '.join(key_params)}) "
            f"AND rca.normalized_value IN ({', '.join(value_params)}))"
        )

    predicate = (
        " AND EXISTS (SELECT 1 FROM recommendation_catalog_chunk_mappings rcm "
        "JOIN recommendation_catalog_entries rce ON rce.id = rcm.catalog_entry_id "
        f"WHERE rcm.document_chunk_id = {chunk_id_expression} AND "
        + " AND ".join(conditions)
        + ")"
    )
    if (
        normalized_skus
        and not attrs
        and object_type in (None, "product")
        and chunk_content_expression is not None
    ):
        legacy_sku_conditions = []
        for index, value in enumerate(normalized_skus):
            key = f"legacy_sku_exact_{index}"
            if dialect_name == "sqlite":
                params[key] = value
                legacy_sku_conditions.append(
                    f"rag_exact_sku(COALESCE({chunk_content_expression}, ''), :{key}) = 1"
                )
            else:
                params[key] = r"(^|[^[:alnum:]_-])" + re.escape(value) + r"([^[:alnum:]_-]|$)"
                legacy_sku_conditions.append(f"COALESCE({chunk_content_expression}, '') ~* :{key}")
        legacy_predicate = (
            "NOT EXISTS (SELECT 1 FROM recommendation_catalog_chunk_mappings rcm_legacy "
            f"WHERE rcm_legacy.document_chunk_id = {chunk_id_expression}) AND ("
            + " OR ".join(legacy_sku_conditions)
            + ")"
        )
        predicate = (
            " AND ((EXISTS (SELECT 1 FROM recommendation_catalog_chunk_mappings rcm "
            "JOIN recommendation_catalog_entries rce ON rce.id = rcm.catalog_entry_id "
            f"WHERE rcm.document_chunk_id = {chunk_id_expression} AND "
            + " AND ".join(conditions)
            + ")) OR ("
            + legacy_predicate
            + "))"
        )
    return predicate, params
