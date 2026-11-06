"""Bounded, read-only search of authoritative tenant offerings.

Search results are candidates, never the entire catalog or fitment evidence.
Exact workflow references deliberately do not depend on a search window.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from sqlalchemy import String, and_, case, cast, false, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from app.models.industry_modules import AppointmentService
from app.models.sales import Product
from app.rag.catalog_filters import (
    attribute_key_aliases, attribute_value_aliases, extract_query_hard_filters,
    validate_hard_filters,
)
from app.services.business_profile import get_business_profile
from app.services.product_resolver import (
    find_explicit_product_mentions, normalize_product_text,
)
from app.services.recommendation_artifacts import stated_budget
from app.tenancy.workspace_modules import get_workspace_config


_KINDS = {"goods", "service", "rental"}
_FILLERS = set("anh ban bao ben cai can cho co con cua dang dat dich do duoi gia gi giup hang hien hoi khong la loai lich ma minh mot mua muon nao nhieu o pham san shop tai the thue toi toi_da tra tren tu va voi vu xin xem you your i a an the is are do have want buy price please under budget services service rent rental available catalog".split())


def _product_kind(profile):
    value = Product.metadata_["offering_type"].as_string()
    return case((value.in_(sorted(_KINDS)), value), else_=profile.default_offering_type)


def _offering(row, profile):
    if isinstance(row, Product):
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        kind = meta.get("offering_type")
        if kind not in _KINDS:
            kind = profile.default_offering_type
        return {
            "ref": f"product:{row.id}", "name": row.name, "sku": row.sku,
            "kind": kind, "price": str(row.price),
            "billing_unit": meta.get("billing_unit") or profile.default_billing_unit or ("lần" if kind == "service" else None),
            "available": None if kind == "service" else max(0, int(row.stock_quantity or 0) - int(row.reserved_quantity or 0)),
            "availability_basis": "staff-reviewed schedule" if kind == "service" else "current inventory count; date-specific rental availability is not checked" if kind == "rental" else "current unreserved inventory",
            "description": (row.description or "")[:1000],
        }
    return {
        "ref": f"service:{row.id}", "name": row.name, "kind": "service",
        "price": str(row.price), "billing_unit": profile.default_billing_unit or "lần",
        "duration_minutes": row.duration_minutes, "available": None,
        "availability_basis": "staff-reviewed schedule", "description": (row.description or "")[:1000],
    }


def get_current_offering(db, business_id, ref, profile=None):
    """Return one active tenant-owned ``product:N``/``service:N``, or None.

    No search, pagination, stock filter, commit, or row lock. Workflow callers
    retain their own locks and must re-read this snapshot after locking.
    Appointment services also require the appointments module to be enabled.
    """
    if not isinstance(ref, str) or not re.fullmatch(r"(?:product|service):[1-9][0-9]{0,9}", ref):
        return None
    prefix, identifier = ref.split(":")
    identifier = int(identifier)
    if identifier > 2147483647:
        return None
    if prefix == "service":
        if "appointments" not in get_workspace_config(db, business_id)["enabled_modules"]:
            return None
        model, active = AppointmentService, AppointmentService.is_active.is_(True)
    else:
        model, active = Product, Product.status == "active"
    row = db.query(model).filter(
        model.business_id == business_id, model.id == identifier, active,
    ).populate_existing().first()
    return _offering(row, profile or get_business_profile(db, business_id)) if row is not None else None


def _normalized_sql(value):
    return func.lower(func.trim(cast(value, String)))


def _json_values(db, value):
    """Iterate either a scalar or an array without substring attribute matches."""
    if db.get_bind().dialect.name == "postgresql":
        value = cast(value, JSONB)
        array = case((func.jsonb_typeof(value) == "array", value), else_=func.jsonb_build_array(value))
        return func.jsonb_array_elements_text(array).table_valued("value").render_derived()
    return func.json_each(value).table_valued("value", "type")


def _attribute_predicate(db, key, expected):
    accepted = attribute_value_aliases(key, expected)
    aliases = attribute_key_aliases(key, expected)
    nested = Product.metadata_["attributes"]
    no_nested_value = ~or_(*[nested[alias].as_string().isnot(None) for alias in aliases])
    matches = []
    for alias in aliases:
        for is_nested, source in ((True, nested), (False, Product.metadata_)):
            values = _json_values(db, source[alias])
            actual = _normalized_sql(values.c.value)
            scalar_boolean = false()
            if db.get_bind().dialect.name == "sqlite":
                actual = case((values.c.type == "true", "true"), (values.c.type == "false", "false"), else_=actual)
                if isinstance(expected, bool):
                    # SQLite JSON_EXTRACT turns scalar JSON booleans into 1/0.
                    # Inspect the original JSON type rather than matching 1/0.
                    scalar_boolean = func.json_type(source, "$." + json.dumps(alias, ensure_ascii=False)) == str(expected).lower()
            matches.append(select(1).select_from(values).where(
                or_(actual.in_(accepted), scalar_boolean),
                literal(True) if is_nested else no_nested_value,
            ).correlate(Product).exists())
    return or_(*matches)


def _phrase_in_query(db, value, query):
    haystack = literal(" " + query.strip(" .!?;\n\t").casefold() + " ")
    needle = literal(" ") + _normalized_sql(value) + literal(" ")
    position = func.strpos(haystack, needle) if db.get_bind().dialect.name == "postgresql" else func.instr(haystack, needle)
    return and_(_normalized_sql(value) != "", position > 0)


def _lexical_predicates(db, model, query):
    # Keep original accented tokens alongside resolver normalization. SQL uses
    # the installed DB collation; no unaccent extension is required.
    tokens = []
    for raw in re.findall(r"[^\W_]+", query.casefold()):
        folded = normalize_product_text(raw)
        if folded and folded not in _FILLERS and not folded.isdigit() and len(folded) > 1:
            tokens.extend((raw, folded))
    tokens = list(dict.fromkeys(tokens))
    names = [_normalized_sql(model.name), _normalized_sql(func.coalesce(model.description, ""))]
    if model is Product:
        names.append(_normalized_sql(model.sku))
    lexical = [value.contains(token, autoescape=True) for value in names for token in tokens]
    if model is Product:
        for key in ("aliases", "search_terms", "keywords"):
            values = _json_values(db, Product.metadata_[key])
            lexical.append(select(1).select_from(values).where(or_(
                *[_normalized_sql(values.c.value).contains(token, autoescape=True) for token in tokens],
            )).correlate(Product).exists() if tokens else false())
    # Exact SKU/name hits sort ahead of weaker category/description hits BEFORE
    # LIMIT; a late SKU cannot be crowded out by the first hundred rows.
    identity = _phrase_in_query(db, model.name, query)
    sku_identity = false()
    if model is Product:
        words = re.findall(r"[\w]+(?:[-_.][\w]+)*", query.casefold())
        sku_identity = _normalized_sql(model.sku).in_(words + [query.strip().casefold()])
        aliases = _json_values(db, Product.metadata_["aliases"])
        identity = or_(identity, select(1).select_from(aliases).where(
            _phrase_in_query(db, aliases.c.value, query),
        ).correlate(Product).exists())
    rank = case((sku_identity, 0), (identity, 1), else_=2)
    return or_(sku_identity, identity, *lexical) if tokens else None, rank


def _search_text(query, filters):
    # Attribute labels/values and price ceilings already have SQL predicates.
    # Remove only those phrases, so remaining product words still constrain
    # the category rather than admitting every item with the same color/size.
    text = re.sub(
        r"(?:tầm|khoảng|dưới|tối đa|ngân sách|budget|under|up to|<=|≤)\s*"
        r"(?:\d{1,3}(?:[.,]\d{3})*|\d+(?:[.,]\d+)?)\s*(?:k|nghìn|ngàn|tr|triệu|đồng|đ|vnd)?\b",
        " ", query, flags=re.I,
    )
    for key, expected in filters.get("required_attributes", {}).items():
        for label in attribute_key_aliases(key, expected):
            for value in sorted({str(expected), *attribute_value_aliases(key, expected)}, key=len, reverse=True):
                text = re.sub(r"(?<!\w)" + re.escape(label.replace("_", " ")) + r"\s*[:=]?\s*" + re.escape(value) + r"(?!\w)", " ", text, flags=re.I)
    return text


def search_current_offerings(db, business_id, query, limit=12, *, profile=None,
                             hard_filters=None, kind=None, budget=None, offset=0):
    """Return <= limit current offering dictionaries, with filters before LIMIT.

    ``limit`` is 1..100, ``offset`` is a nonnegative page offset. ``kind`` is
    goods/service/rental. ``hard_filters`` reuses the RAG contract: object_type
    (product/service/rental), sku (one or <=10 exact codes), required_attributes.
    Product object_type means the Product table, including service/rental rows;
    kind instead describes business behavior. Explicit caller filters override
    inferred query attributes. Budget is an inclusive per-unit price ceiling,
    inferred by the existing parser if omitted; it never computes a basket.
    Unknown attributes fail closed; names/descriptions do not prove fitment.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a nonnegative integer")
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    if kind is not None and kind not in _KINDS:
        raise ValueError("kind must be goods, service, or rental")
    supplied = validate_hard_filters(hard_filters)
    filters = extract_query_hard_filters(query)
    filters["required_attributes"] = {**filters.get("required_attributes", {}), **supplied.get("required_attributes", {})}
    filters.update({key: value for key, value in supplied.items() if key != "required_attributes"})
    # Labelled identifiers are exact even when they do not contain hyphens.
    labelled = re.search(r"\b(?:sku|mã(?: hàng| sản phẩm)?|code)\s*[:#]?\s*([\w]+(?:[-_.][\w]+)*)", query, re.I)
    if labelled and "sku" not in filters:
        filters["sku"] = labelled.group(1)
    filters = validate_hard_filters(filters)
    budget = stated_budget(query) if budget is None else budget
    if budget is not None:
        try:
            budget = Decimal(str(budget))
        except (InvalidOperation, ValueError):
            raise ValueError("budget must be finite and nonnegative") from None
        if not budget.is_finite() or budget < 0:
            raise ValueError("budget must be finite and nonnegative")
    profile = profile or get_business_profile(db, business_id)
    modules = get_workspace_config(db, business_id)["enabled_modules"]
    queries = []
    for model in (Product, AppointmentService):
        product = model is Product
        object_type = filters.get("object_type")
        if not product and ("appointments" not in modules or kind not in (None, "service") or object_type in ("product", "rental") or filters.get("sku")):
            continue
        if product and object_type == "service":
            continue
        statement = select(model.id.label("id"), literal("product" if product else "service").label("source"))
        statement = statement.where(model.business_id == business_id, Product.status == "active" if product else AppointmentService.is_active.is_(True))
        if product:
            if kind is not None:
                statement = statement.where(_product_kind(profile) == kind)
            if object_type == "rental":
                statement = statement.where(_product_kind(profile) == "rental")
        if budget is not None:
            statement = statement.where(model.price <= budget)
        if filters.get("sku"):
            statement = statement.where(_normalized_sql(Product.sku).in_([code.casefold() for code in filters["sku"]]))
        for key, expected in filters.get("required_attributes", {}).items():
            if product:
                statement = statement.where(_attribute_predicate(db, key, expected))
            elif key == "duration_minutes":
                statement = statement.where(cast(AppointmentService.duration_minutes, String).in_(attribute_value_aliases(key, expected)))
            else:
                statement = statement.where(false())
        lexical, rank = _lexical_predicates(db, model, _search_text(query, filters))
        # An exact SKU is sufficient identity; other remaining product words
        # still constrain attribute-only searches.
        if lexical is not None and not filters.get("sku"):
            statement = statement.where(lexical)
        queries.append(statement.add_columns(rank.label("rank")))
    if not queries:
        return []
    candidates = queries[0].union_all(*queries[1:]).subquery()
    selected = db.execute(select(candidates).order_by(
        candidates.c.rank, candidates.c.source, candidates.c.id,
    ).offset(offset).limit(limit)).all()
    # Hydrate only the selected page, retaining authoritative prices and stock.
    product_ids = [row.id for row in selected if row.source == "product"]
    service_ids = [row.id for row in selected if row.source == "service"]
    products = db.query(Product).filter(
        Product.business_id == business_id, Product.status == "active", Product.id.in_(product_ids),
    ).populate_existing().all() if product_ids else []
    services = db.query(AppointmentService).filter(
        AppointmentService.business_id == business_id, AppointmentService.is_active.is_(True), AppointmentService.id.in_(service_ids),
    ).populate_existing().all() if service_ids else []
    by_ref = {item["ref"]: item for item in (_offering(row, profile) for row in [*products, *services])}
    # Reuse conservative identity resolution to order this bounded page only.
    explicit = {f"product:{row.id}" for row in find_explicit_product_mentions(products, query)}
    result = [by_ref[f"{row.source}:{row.id}"] for row in selected if f"{row.source}:{row.id}" in by_ref]
    return sorted(result, key=lambda item: item["ref"] not in explicit)
