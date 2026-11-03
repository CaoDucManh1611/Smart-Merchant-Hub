"""Tenant-safe catalog predicates applied inside retrieval SQL before LIMIT."""
from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import re
import math
from typing import Any


_OBJECT_TYPES = {"product", "service", "rental"}
_CHUNK_ID_EXPRESSIONS = {"dc.id", "sc.id"}
_CHUNK_CONTENT_EXPRESSIONS = {"dc.content", "sc.content"}
_CHUNK_METADATA_EXPRESSIONS = {"dc.metadata", "sc.metadata"}
_ATTRIBUTE_KEY_ALIASES = {
    "size": ("size", "sizes", "kich_thuoc", "kich thuoc", "kích_thước", "kích thước"),
    "volume": ("volume", "capacity", "dung_tich", "dung tích", "thể_tích", "thể tích"),
    "duration_minutes": (
        "duration_minutes", "duration", "minutes", "so_phut", "số phút",
        "thoi_luong", "thời lượng",
    ),
    "vehicle_model": (
        "vehicle_model", "vehicle model", "compatible_model", "compatible model",
        "dong_xe", "dòng xe", "mau_xe", "mẫu xe", "xe_tuong_thich", "xe tương thích",
    ),
    "vehicle_make": (
        "vehicle_make", "vehicle make", "hang_xe", "hãng xe", "thuong_hieu_xe",
        "thương hiệu xe",
    ),
    "vehicle_year": (
        "vehicle_year", "vehicle year", "model_year", "model year", "nam_xe", "năm xe",
        "doi_xe", "đời xe",
    ),
    "room_type": ("room_type", "room type", "loai_phong", "loại phòng", "hang_phong", "hạng phòng"),
    "material": ("material", "chat_lieu", "chất liệu", "fabric", "vật liệu", "vat_lieu"),
    "brand": ("brand", "thuong_hieu", "thương hiệu", "nhan_hieu", "nhãn hiệu"),
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
_NON_ATTRIBUTE_FIELDS = {
    "sku", "product_id", "item_id", "code", "ma", "ma_san_pham", "ma_hang",
    "price", "cost", "gia", "gia_ban", "budget", "ngan_sach", "stock",
    "inventory", "ton_kho", "so_luong", "availability", "trang_thai", "status",
}
_QUERY_WORDS_NOT_ATTRIBUTE_LABELS = {
    "toi", "minh", "ban", "shop", "khach", "hoi", "tim", "muon", "can", "cho",
}
_NON_ATTRIBUTE_FIELD_WORDS = {
    "price", "gia", "cost", "budget", "stock", "inventory", "ton", "kho",
    "availability", "status", "sku", "code", "ma", "id",
}


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return " ".join(text.split())


def extract_query_hard_filters(query: str, *, object_type: str | None = None) -> dict[str, Any]:
    """Extract explicit common and ``attribute: value`` catalog constraints."""
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
        # A bare "xanh" may mean blue or green; leave it as soft query text.
        if canonical is not None:
            filters.setdefault("required_attributes", {})["color"] = canonical

    # Generic industry attributes (for example ``duration: 60 minutes`` or
    # ``vehicle model: Wave Alpha``) are accepted only when the customer
    # explicitly labels the value. Price, stock and identity fields are read
    # from their authoritative paths, never treated as free-form attributes.
    for match in re.finditer(
        r"(?P<key>[\wÀ-ỹ][\wÀ-ỹ _-]{0,39})\s*[:=]\s*(?P<value>[^,;\n?]{1,80})",
        str(query or ""),
        re.UNICODE,
    ):
        key = " ".join(match.group("key").strip(" _-").split())
        value = match.group("value").strip().strip(" .!?\"'“”‘’")
        folded_key = re.sub(r"[^a-z0-9]+", "_", _fold(key)).strip("_")
        key_words = set(folded_key.split("_"))
        if (
            not key or not value or len(value) > 80
            or len(key.split()) > 4
            or not is_known_attribute_key(key)
            or folded_key in _NON_ATTRIBUTE_FIELDS
            or key_words & _NON_ATTRIBUTE_FIELD_WORDS
            or key_words & _QUERY_WORDS_NOT_ATTRIBUTE_LABELS
        ):
            continue
        filters.setdefault("required_attributes", {}).setdefault(canonical_attribute_key(key), value)
    return filters


def _fold(value: str) -> str:
    """Fold accents for comparing explicit labels with reserved field names."""
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold()).replace("đ", "d")
    return "".join(char for char in normalized if not unicodedata.combining(char))


def canonical_attribute_key(key: str) -> str:
    """Normalize an attribute label to the catalog's canonical key when known."""
    normalized_key = _normalize(key).replace(" ", "_")
    return next(
        (
            canonical
            for canonical, aliases in _ATTRIBUTE_KEY_ALIASES.items()
            if normalized_key in {_normalize(alias).replace(" ", "_") for alias in aliases}
        ),
        normalized_key,
    )


def is_known_attribute_key(key: str) -> bool:
    normalized_key = _normalize(key).replace(" ", "_")
    return any(
        normalized_key == _normalize(alias).replace(" ", "_")
        for aliases in _ATTRIBUTE_KEY_ALIASES.values()
        for alias in aliases
    )


def validate_hard_filters(hard_filters: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate the small structured filter contract before SQL construction."""
    if hard_filters is None:
        return {}
    if not isinstance(hard_filters, Mapping):
        raise ValueError("hard_filters must be a mapping")
    allowed = {"object_type", "sku", "required_attributes"}
    unknown = set(hard_filters) - allowed
    if unknown:
        raise ValueError(f"unsupported hard filters: {sorted(unknown)}")

    validated: dict[str, Any] = {}
    object_type = hard_filters.get("object_type")
    if object_type is not None:
        normalized_type = _normalize(object_type)
        if normalized_type not in _OBJECT_TYPES:
            raise ValueError("object_type must be product, service, or rental")
        validated["object_type"] = normalized_type

    sku = hard_filters.get("sku")
    if sku is not None:
        values = sku if isinstance(sku, (list, tuple, set, frozenset)) else [sku]
        clean_skus = []
        for value in values:
            if not isinstance(value, (str, int)) or not str(value).strip() or len(str(value).strip()) > 120:
                raise ValueError("sku filters must be non-empty strings up to 120 characters")
            clean_skus.append(str(value).strip())
        if not clean_skus or len(clean_skus) > 10:
            raise ValueError("sku filters must contain between 1 and 10 values")
        validated["sku"] = list(dict.fromkeys(clean_skus))

    attributes = hard_filters.get("required_attributes")
    if attributes is not None:
        if not isinstance(attributes, Mapping):
            raise ValueError("required_attributes must be a key/value mapping")
        if len(attributes) > 12:
            raise ValueError("at most 12 required attributes are supported")
        clean_attributes: dict[str, str | int | float | bool] = {}
        for key, value in attributes.items():
            if not isinstance(key, str) or not key.strip() or len(key.strip()) > 100:
                raise ValueError("attribute keys must be non-empty strings up to 100 characters")
            if isinstance(value, bool):
                clean_value: str | int | float | bool = value
            elif isinstance(value, (str, int, float)):
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("attribute values must be finite")
                if not str(value).strip() or len(str(value).strip()) > 255:
                    raise ValueError("attribute values must be non-empty and at most 255 characters")
                clean_value = value.strip() if isinstance(value, str) else value
            else:
                raise ValueError("attribute values must be scalar strings, numbers, or booleans")
            clean_attributes[canonical_attribute_key(key)] = clean_value
        if clean_attributes:
            validated["required_attributes"] = clean_attributes
    return validated


def _attribute_key_values(key: str, value: Any) -> tuple[list[str], list[str]]:
    normalized_key = canonical_attribute_key(key)
    normalized_value = _normalize(value)
    key_aliases = _attribute_key_aliases_for_value(normalized_key, value)
    value_aliases = (normalized_value,)
    if normalized_key == "duration_minutes":
        duration = re.fullmatch(
            r"\s*(\d+(?:[.,]\d+)?)\s*(seconds?|secs?|giây|giay|minutes?|mins?|phút|phut|hours?|hrs?|giờ|gio)\s*",
            _fold(normalized_value),
        )
        if duration:
            try:
                amount = Decimal(duration.group(1).replace(",", "."))
                unit = duration.group(2)
                if unit.startswith(("second", "sec", "giay")):
                    minutes = amount / Decimal(60)
                elif unit.startswith(("hour", "hr", "gio")):
                    minutes = amount * Decimal(60)
                else:
                    minutes = amount
                if minutes == minutes.to_integral_value():
                    value_aliases = (str(int(minutes)),)
            except InvalidOperation:
                pass
    if normalized_key == "color":
        value_aliases = next(
            (aliases for canonical, aliases in _COLOR_VALUE_ALIASES.items() if normalized_value == canonical),
            value_aliases,
        )
    return [
        _normalize(alias).replace(" ", "_") for alias in key_aliases
    ], [_normalize(alias) for alias in value_aliases]


def _has_explicit_volume_unit(value: Any) -> bool:
    return bool(re.search(
        r"\b\d+(?:[.,]\d+)?\s*(?:millilit(?:er|re)s?|ml|cl|dl|lit|liters?|litres?)\b",
        _fold(str(value)),
    ))


def _attribute_key_aliases_for_value(key: str, value: Any = None) -> tuple[str, ...]:
    normalized_key = canonical_attribute_key(key)
    aliases = _ATTRIBUTE_KEY_ALIASES.get(normalized_key, (normalized_key,))
    if normalized_key == "volume" and _has_explicit_volume_unit(value):
        aliases = (*aliases, "size", "sizes", "kich_thuoc", "kích thước")
    return tuple(_normalize(alias) for alias in aliases)


def attribute_key_aliases(key: str, value: Any = None) -> tuple[str, ...]:
    return _attribute_key_aliases_for_value(key, value)


def attribute_value_aliases(key: str, value: Any) -> tuple[str, ...]:
    return tuple(_attribute_key_values(key, value)[1])


def catalog_hard_filter_sql(
    hard_filters: Mapping[str, Any] | None,
    *,
    chunk_id_expression: str,
    chunk_content_expression: str | None = None,
    chunk_metadata_expression: str | None = None,
    preserve_policy_sources: bool = False,
    allow_unmapped_lexical_sku: bool = False,
    dialect_name: str = "postgresql",
) -> tuple[str, dict[str, Any]]:
    """Return bound SQL that keeps catalog-mapped chunks isolated to matching entries.

    A shared chunk is rejected when any product/service/rental mapping on that chunk
    violates the requested hard filter. This prevents one matching SKU from making
    unrelated text in a mixed-product chunk eligible before retrieval LIMIT.
    """
    if not hard_filters:
        return "", {}
    if chunk_id_expression not in _CHUNK_ID_EXPRESSIONS:
        raise ValueError("unsupported chunk alias")
    if chunk_content_expression is not None and chunk_content_expression not in _CHUNK_CONTENT_EXPRESSIONS:
        raise ValueError("unsupported chunk content alias")
    if chunk_metadata_expression is not None and chunk_metadata_expression not in _CHUNK_METADATA_EXPRESSIONS:
        raise ValueError("unsupported chunk metadata alias")
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
    object_type = hard_filters.get("object_type")
    object_type_condition: str | None = None
    if object_type is not None:
        object_type = _normalize(object_type)
        if object_type not in _OBJECT_TYPES:
            raise ValueError("object_type must be product, service, or rental")
        object_type_condition = "{alias}.object_type = :hard_filter_object_type"
        params["hard_filter_object_type"] = object_type

    normalized_skus: list[str] = []
    sku_condition: str | None = None
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
        sku_condition = f"{{alias}}.sku_norm IN ({', '.join(keys)})"

    attrs = hard_filters.get("required_attributes") or {}
    if not isinstance(attrs, Mapping):
        raise ValueError("required_attributes must be a key/value mapping")
    attribute_conditions: list[str] = []
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
        attribute_conditions.append(
            "EXISTS (SELECT 1 FROM recommendation_catalog_attributes rca "
            "WHERE rca.catalog_entry_id = {alias}.id "
            f"AND rca.key_norm IN ({', '.join(key_params)}) "
            f"AND rca.normalized_value IN ({', '.join(value_params)}))"
        )

    def entry_conditions(alias: str) -> list[str]:
        conditions = [f"{alias}.business_id = :business_id"]
        if object_type is not None:
            conditions.append(object_type_condition.format(alias=alias))
        if normalized_skus:
            conditions.append(sku_condition.format(alias=alias))
        conditions.extend(condition.format(alias=alias) for condition in attribute_conditions)
        return conditions

    conditions = entry_conditions("rce")
    isolated_mapping_predicate = (
        "NOT EXISTS (SELECT 1 FROM recommendation_catalog_chunk_mappings rcm_other "
        "JOIN recommendation_catalog_entries rce_other ON rce_other.id = rcm_other.catalog_entry_id "
        f"WHERE rcm_other.document_chunk_id = {chunk_id_expression} "
        "AND NOT COALESCE(("
        + " AND ".join(entry_conditions("rce_other"))
        + "), FALSE))"
    )

    catalog_predicate = (
        "EXISTS (SELECT 1 FROM recommendation_catalog_chunk_mappings rcm "
        "JOIN recommendation_catalog_entries rce ON rce.id = rcm.catalog_entry_id "
        f"WHERE rcm.document_chunk_id = {chunk_id_expression} AND "
        + " AND ".join(conditions)
        + ") AND ("
        + isolated_mapping_predicate
        + ")"
    )

    # Older knowledge chunks may contain a clearly labelled SKU but have no
    # catalog mapping yet. Lexical retrieval can admit those candidates because
    # its SQL also requires the queried SKU text and Python applies a bounded,
    # exact identifier check before returning them. Never enable this for vector
    # retrieval or alongside additional hard filters.
    allow_unmapped_sku = bool(
        allow_unmapped_lexical_sku
        and normalized_skus
        and chunk_content_expression is not None
        and object_type is None
        and not attrs
    )
    unmapped_sku_predicate = (
        "NOT EXISTS (SELECT 1 FROM recommendation_catalog_chunk_mappings rcm_unmapped_sku "
        f"WHERE rcm_unmapped_sku.document_chunk_id = {chunk_id_expression})"
    ) if allow_unmapped_sku else None

    preserve_unmapped_policy = bool(preserve_policy_sources and chunk_metadata_expression is not None)
    policy_predicate = None
    if preserve_unmapped_policy:
        topic_expression = (
            f"COALESCE(json_extract({chunk_metadata_expression}, '$.topic'), '')"
            if dialect_name == "sqlite"
            else f"COALESCE({chunk_metadata_expression}->>'topic', '')"
        )
        policy_predicate = (
            "NOT EXISTS (SELECT 1 FROM recommendation_catalog_chunk_mappings rcm_policy "
            f"WHERE rcm_policy.document_chunk_id = {chunk_id_expression}) AND "
            f"{topic_expression} IN ('returns', 'delivery', 'payments', 'faq', 'shop')"
        )
        permitted = [catalog_predicate, policy_predicate]
        if unmapped_sku_predicate:
            permitted.append(unmapped_sku_predicate)
        predicate = " AND (" + " OR ".join(f"({item})" for item in permitted) + ")"
    else:
        predicate = (
            " AND (" + f"({catalog_predicate}) OR ({unmapped_sku_predicate})" + ")"
            if unmapped_sku_predicate else f" AND {catalog_predicate}"
        )
    return predicate, params
