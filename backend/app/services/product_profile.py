"""Structured, shop-authored product facts shared by details and need matching."""
from app.services.product_resolver import normalize_product_text

PROFILE_FIELDS = (("benefits", "Công dụng"), ("suitable_needs", "Nhu cầu phù hợp"),
                  ("usage", "Cách dùng"), ("warnings", "Lưu ý"))

def profile_values(product, key):
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    profile = metadata.get("product_profile")
    if not isinstance(profile, dict):
        return []
    value = profile.get(key)
    return [v.strip() for v in (value if isinstance(value, list) else [value]) if isinstance(v, str) and v.strip()]

def profile_detail_lines(product):
    lines = []
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    profile = metadata.get("product_profile") or {}
    if isinstance(profile, dict) and profile.get("demo"):
        lines.append("Thông tin minh họa cho sản phẩm demo; chưa phải thông tin nhà sản xuất xác nhận.")
    for key, label in PROFILE_FIELDS:
        values = profile_values(product, key)
        if values:
            lines.append(label + ": " + "; ".join(values))
    return lines

def profile_search_text(product):
    return " ".join(v for key, _ in PROFILE_FIELDS for v in profile_values(product, key))

def matching_need_products(products, query, budget=None):
    """Only return products with an explicitly matched shop-defined need."""
    normalized = " " + normalize_product_text(query) + " "
    explicit_groups = []
    for p in products:
        for category in profile_values(p, "category"):
            folded = normalize_product_text(category)
            if " " + folded + " " in normalized:
                explicit_groups.append((len(folded.split()), folded))
    if explicit_groups:
        specificity = max(score for score, _ in explicit_groups)
        groups = {group for score, group in explicit_groups if score == specificity}
        products = [p for p in products if any(normalize_product_text(c) in groups
                    for c in profile_values(p, "category"))]
    requested_specificity = max(
        (len(normalize_product_text(need).split()) for p in products
         for need in profile_values(p, "suitable_needs")
         if " " + normalize_product_text(need) + " " in normalized), default=0)
    result = []
    for product in products:
        if product.status != "active" or max(0, (product.stock_quantity or 0) - (product.reserved_quantity or 0)) <= 0:
            continue
        if budget is not None and float(product.price) > float(budget):
            continue
        needs = profile_values(product, "suitable_needs")
        scores = [len(normalize_product_text(need).split()) for need in needs
                  if " " + normalize_product_text(need) + " " in normalized]
        if scores:
            result.append((max(scores), product))
    if not result:
        return []
    # A specific need such as lip hydration beats the broader hydration tag.
    best = requested_specificity
    return sorted([p for score, p in result if score == best], key=lambda p: (p.price, p.id))
