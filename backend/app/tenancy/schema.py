"""Deterministic schema naming for tenant data."""

import re


SCHEMA_NAME_RE = re.compile(r"^shop_[1-9][0-9]*$")


def schema_name_for(business_id: int) -> str:
    value = int(business_id)
    if value <= 0:
        raise ValueError("business_id must be a positive integer")
    return f"shop_{value}"


def validate_schema_name(value: str) -> str:
    schema = str(value or "").strip().lower()
    if not SCHEMA_NAME_RE.fullmatch(schema):
        raise ValueError("schema_name must match shop_<business_id>")
    return schema
