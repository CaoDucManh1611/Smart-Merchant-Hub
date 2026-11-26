"""Answer broad catalog questions from current shop data."""

import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone

from app.models.sales import Product


def _product_group_query(text: str) -> str | None:
    """Extract a product family/category such as ``serum`` or ``toner``."""
    from app.services.product_resolver import normalize_product_text

    normalized = normalize_product_text(str(text or "")).rstrip(" ?.!,").strip()
    patterns = (
        r"\b(?:(?:cac|nhung)\s+)?(?:loai|mau|dong|nhom)\s+(.+?)"
        r"(?=\s+(?:nao|gi|di|nhe|nhi|vay|nha|a|dang|hien|co|"
        r"ben minh|cua shop|shop|trong shop)\b|$)",
        r"\b(?:cac|nhung)\s+(?:san pham|mat hang)\s+(.+?)"
        r"(?=\s+(?:nao|gi|dang|hien|co|ben minh|cua shop|shop|trong shop)\b|$)",
    )
    match = next((result for pattern in patterns if (result := re.search(pattern, normalized))), None)
    if not match:
        return None
    term = match.group(1).strip()
    term = re.sub(r"^(?:san pham|mat hang)\s+", "", term)
    term = re.sub(r"\s+(?:nao|gi)$", "", term).strip()
    if term in {"san pham", "mat hang", "hang hoa", "do", "nao", "gi"}:
        return None
    non_category_words = {
        "tat", "ca", "cac", "nhung", "san", "pham", "mat", "hang", "hoa",
        "co", "trong", "shop", "ban", "cua", "o", "hien", "dang", "nao",
        "gi", "khong", "duoc", "nha", "vay", "nhi", "di", "ben", "minh",
        "toi", "muon", "xem", "voi", "nhe", "xin", "giup", "ho",
    }
    if not (set(term.split()) - non_category_words):
        return None
    return term or None


def catalog_overview_kind(text: str) -> str | None:
    """Route shop overview, full product lists, and category browsing separately."""
    from app.services.product_resolver import normalize_product_text
    from app.services.auto_reply_service import (
        _policy_kind, _is_payment_method_policy_question, _is_shop_promotion_question,
    )
    from app.services.customer_order_service import detect_customer_order_intent

    normalized = normalize_product_text(str(text or "")).rstrip(" ?.!,").strip()
    # Mixed business questions need their policy/service/order route to retain
    # the whole request instead of returning only a product overview.
    if (_policy_kind(text) or _is_payment_method_policy_question(text)
        or _is_shop_promotion_question(text) or detect_customer_order_intent(text) or re.search(
        r"\b(?:dich vu|dat lich|lich hen|cho thue|don hang|hoa don|thanh toan|"
        r"chuyen khoan|tien mat|cod|vietqr|gio mo cua|dia chi|shipping|delivery|payment|"
        r"sua chua|sua xe|bao duong|massage|repair|maintenance|thue xe|thue phong|thue may|"
        r"ma don|don (?:cua|nay|do|ay)|service|services|rental|appointment|order|invoice|"
        r"opening hours|address)\b", normalized,
    )):
        return None
    if re.search(r"\b(con hang|ton kho|bao nhieu|het hang|dat mua|dat hang|chot don|huy don|doi tra|bao hanh|so sanh|duoi|gia|phu hop)\b", normalized):
        return None
    # Generic shop questions and short catalogue follow-ups. Deliberately
    # exclude product-specific details and purchase verbs from this route.
    if re.search(
        r"\b(?:chi tiet|thanh phan|cach dung|cong dung|tac dung|dung the nao|dung ra sao|mua|lay)\b",
        normalized,
    ) or re.search(r"\b(?:loai|mau|san pham)\s+(?:do|nay|ay|vua hoi)\b", normalized):
        return None
    if _product_group_query(normalized):
        return "product_group"
    if (
        re.search(r"\b(?:tat ca|toan bo|danh sach|liet ke)\b.*\b(?:cac\s+)?(?:san pham|mat hang)\b", normalized)
        or re.search(
            r"\b(?:ban|shop|cua hang)\b.*\bco\s+(?:nhung|cac)\s+(?:san pham|mat hang)\s+(?:nao|gi)\b",
            normalized,
        )
        or re.search(r"\b(?:nhung|cac)\s+(?:san pham|mat hang)\s+(?:hien|dang)\s+(?:co|ban)\b", normalized)
    ):
        return "product_list"
    # Customers often phrase this as a question about what the shop mainly
    # sells, rather than asking for a formal product list. Keep it on the
    # deterministic, tenant-scoped catalog path instead of the AI fallback.
    if re.search(
        r"\b(?:shop|cua hang|he thong)\b.*\b(?:kinh doanh|buon ban|ban)\b"
        r"\s+(?:ve\s+)?(?:nhung\s+|cac\s+)?"
        r"(?:gi|j|cai gi|mat hang gi|san pham gi|hang hoa gi|"
        r"loai gi|mat hang nao|san pham nao|hang hoa nao|loai nao)\b",
        normalized,
    ):
        return "products"
    if re.search(r"\b(?:shop|cua hang)\b.*\b(?:co|ban|kinh doanh)\s+(?:nhung\s+)?(?:gi|j)\b", normalized):
        return "products"
    if re.search(r"\bben\s+(?:ban|minh|em|anh|chi)\s+(?:dang\s+|hien\s+)?(?:co|ban|kinh doanh)\s+(?:nhung\s+)?(?:gi|j)\b", normalized):
        return "products"
    if re.search(r"\b(?:xem|liet ke|gioi thieu)\s+(?:giup\s+)?(?:tat ca\s+|cac\s+|nhung\s+)?(?:hang|mat hang|san pham)\s+(?:dang ban|hien co|cua shop)\b", normalized):
        return "products"
    if re.fullmatch(r"(?:gom|bao gom)(?:\s+co)?\s+(?:nhung\s+)?(?:gi|j)(?:\s+(?:v|vay|a|nhi|the))?", normalized):
        return "products"
    if re.search(r"\b(danh muc|nhom san pham)\s+(nao|gi)\b|\b(danh sach|liet ke)\s+(cac\s+)?danh muc\b", normalized):
        return "categories"
    if re.search(r"\bloai\s+(?:mat hang|san pham)\s+(?:gi|nao)\b", normalized):
        return "categories"
    if re.search(r"\b(?:(?:ban|kinh doanh)\s+|(?:ban|kinh doanh|co)\s+(?:nhung\s+|cac\s+)?(?:mat hang|san pham)\s+)(?:gi|j|nao)(?:\s+(?:vay|v|a))?$", normalized):
        return "products"
    return None


def render_catalog_overview(db, business_id: int, kind: str, *, query: str | None = None) -> str:
    products = db.query(Product).filter(
        Product.business_id == business_id, Product.status == "active",
    ).order_by(Product.name, Product.id).all()
    products = [
        product for product in products
        if (product.metadata_ if isinstance(product.metadata_, dict) else {}).get("offering_type")
        not in {"service", "rental"}
    ]
    if not products:
        return "Shop chưa có sản phẩm nào đang mở bán. Bạn cần tìm gì để mình nhờ nhân viên hỗ trợ nhé?"
    if kind == "product_group":
        from app.services.product_resolver import normalize_product_text

        term = _product_group_query(query or "")
        if not term:
            return "Bạn cho mình biết nhóm sản phẩm muốn xem nhé."
        terms = [part for part in term.split() if len(part) > 1]
        matched = []
        for product in products:
            metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
            if metadata.get("offering_type") in {"service", "rental"}:
                continue
            attributes = metadata.get("attributes") if isinstance(metadata.get("attributes"), dict) else {}
            searchable = [product.name]
            for key in ("aliases", "search_terms", "keywords"):
                value = metadata.get(key)
                searchable.extend(value if isinstance(value, list) else [value] if isinstance(value, str) else [])
            for key in ("category", "product_type"):
                value = attributes.get(key) or metadata.get(key)
                searchable.extend(value if isinstance(value, list) else [value] if isinstance(value, str) else [])
            normalized_catalog_text = " ".join(normalize_product_text(str(value)) for value in searchable if value)
            if all(re.search(rf"(?<!\w){re.escape(part)}(?!\w)", normalized_catalog_text) for part in terms):
                matched.append(product)
        names = list(dict.fromkeys(product.name for product in matched))
        if not names:
            return "Mình chưa thấy sản phẩm thuộc nhóm bạn hỏi trong danh mục đang bán. Bạn muốn tìm hiểu nhóm nào khác ạ?"
        lines = [f"Dạ, shop đang có {len(names)} sản phẩm trong nhóm này:"]
        lines.extend(f"• {name}" for name in names)
        lines.append("Bạn muốn xem mẫu nào để mình giới thiệu cụ thể hơn ạ?")
        return "\n".join(lines)
    if kind == "product_list":
        names = list(dict.fromkeys(product.name for product in products))
        if not names:
            return "Shop chưa có sản phẩm nào đang mở bán. Bạn muốn tìm nhóm hàng nào ạ?"
        lines = [f"Shop hiện có {len(names)} sản phẩm đang mở bán:"]
        lines.extend(f"• {name}" for name in names)
        return "\n".join(lines)
    if kind == "categories":
        categories = {}
        for product in products:
            metadata = product.metadata_ or {}
            attributes = metadata.get("attributes") or {}
            values = attributes.get("category") if isinstance(attributes, dict) else None
            for value in values if isinstance(values, list) else [values]:
                if isinstance(value, str) and value.strip():
                    label = value.strip()
                    categories.setdefault(label.casefold(), label)
        if not categories:
            return "Shop có sản phẩm đang bán nhưng chưa phân danh mục. Bạn có muốn xem tên sản phẩm không?"
        names = sorted(categories.values(), key=str.casefold)
        return "Shop hiện có các danh mục sau:\n" + "\n".join(f"• {name}" for name in names[:15])
    from app.services.product_resolver import product_family
    families = {product_family(p).casefold(): product_family(p) for p in products
                if (p.metadata_ or {}).get('offering_type') not in {'service', 'rental'}}

    main_groups = sorted(families.values(), key=str.casefold)
    lines = ["Shop hiện đang kinh doanh các nhóm chính sau:"]
    lines.extend(f"• {name}" for name in main_groups[:15])
    if len(main_groups) > 15:
        lines.append(f"• Và {len(main_groups) - 15} nhóm sản phẩm khác")
    lines.append("Bạn quan tâm nhóm nào để mình giới thiệu sản phẩm cụ thể ạ?")
    return "\n".join(lines)


def render_service_overview(db, business_id: int) -> str:
    """List active appointment services with their configured price and duration."""
    from app.models.industry_modules import AppointmentService

    services = db.query(AppointmentService).filter(
        AppointmentService.business_id == business_id,
        AppointmentService.is_active.is_(True),
    ).order_by(AppointmentService.name, AppointmentService.id).all()
    if not services:
        return "Hiện shop chưa có dịch vụ nào đang nhận lịch. Bạn muốn mình nhờ nhân viên tư vấn thêm không?"

    lines = ["Shop hiện đang cung cấp các dịch vụ sau:"]
    for service in services:
        try:
            amount = f"{int(round(float(service.price or 0))):,}".replace(",", ".")
        except (TypeError, ValueError, OverflowError):
            amount = "chưa cập nhật"
        duration = service.duration_minutes
        duration_text = f"{duration} phút" if duration else "chưa cập nhật thời lượng"
        lines.append(f"• {service.name} — {amount} đồng · {duration_text}")
    lines.append("Bạn muốn tìm hiểu hoặc đặt lịch dịch vụ nào ạ?")
    return "\n".join(lines)


def render_service_catalog_reply(db, business_id: int, text: str, *, conversation_id: int | None = None) -> str | None:
    """Answer read-only service questions from the active service catalog.

    A service question must never fall through to product recommendation or
    checkout. Recent messages are used only to resolve short follow-ups such
    as “dịch vụ đó” or “hai lần hết bao nhiêu?”.
    """
    from app.models.industry_modules import AppointmentService
    from app.models.message import Message
    from app.services.product_resolver import normalize_product_text

    query = normalize_product_text(text)
    if not query:
        return None

    # Booking and availability turns belong to their dedicated workflows.
    if re.search(r"\b(?:dat lich|dat hen|book appointment|book a slot|book now)\b", query):
        return None
    if any(cue in query for cue in (
        "kiem tra lich", "lich trong", "con lich", "available on", "check availability",
    )):
        return None
    if any(cue in query for cue in ("mua ", "dat mua", "dat hang", "chot don", "checkout", "buy ", "order now")):
        return None

    services = db.query(AppointmentService).filter(
        AppointmentService.business_id == business_id,
        AppointmentService.is_active.is_(True),
    ).order_by(AppointmentService.name, AppointmentService.id).all()

    def service_mentions(value: str):
        folded = normalize_product_text(value)
        matches = [
            service for service in services
            if normalize_product_text(service.name)
            and re.search(r"(?<!\w)" + re.escape(normalize_product_text(service.name)) + r"(?!\w)", folded)
        ]
        return sorted(matches, key=lambda item: len(normalize_product_text(item.name)), reverse=True)

    exact_targets = service_mentions(query)
    service_cues = (
        "dich vu", "appointment", "service", "dat lich", "lich hen", "sua chua", "bao duong",
    )
    followup_cues = (
        "dich vu do", "dich vu nay", "dich vu ay", "dich vu vua", "vua gioi thieu",
        "ban dau", "nhac lai", "su dung", "tong chi phi", "gia thap hon", "re hon",
        "ngan hon", "thoi gian thuc hien", "bao lau", "gia nay", "gia co dinh",
        "chi phi nay", "moi lan", "moi buoi", "how much for two",
    )
    has_service_wording = any(cue in query for cue in service_cues)
    has_followup_wording = any(cue in query for cue in followup_cues)

    contextual_targets = []
    if conversation_id is not None and has_followup_wording and not exact_targets:
        recent_messages = db.query(Message).filter(
            Message.conversation_id == conversation_id,
        ).order_by(Message.id.desc()).limit(10).all()
        now = datetime.now(timezone.utc)
        for message in recent_messages:
            content = normalize_product_text(message.content or "")
            if not content or content == query:
                continue
            stamp = message.received_at
            if stamp is None:
                break
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if now - stamp > timedelta(minutes=30):
                break
            # A clear switch to shopping or order handling ends service-topic
            # inheritance, so old appointment names cannot hijack later turns.
            if any(cue in content for cue in (
                "san pham", "product", "item", "mua ", "mua hang", "dat mua",
                "dat hang", "chot don", "don hang", "thanh toan", "checkout",
            )):
                break
            mentions = service_mentions(content)
            if mentions:
                contextual_targets = mentions
                break

    has_service_context = bool(has_service_wording or exact_targets or contextual_targets)
    if not has_service_context:
        return None
    if not services:
        asks_service_catalog = any(cue in query for cue in (
            "gia", "price", "chi phi", "bao nhieu", "thoi luong", "bao lau",
            "danh sach", "cac dich vu", "nhung dich vu", "what services",
        ))
        if asks_service_catalog:
            return "Hiện shop chưa có dịch vụ nào đang nhận lịch. Bạn nhắn nhân viên shop để được tư vấn thêm nhé."
        return None

    def price_value(service):
        try:
            return Decimal(str(service.price or 0))
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            return Decimal("0")

    def money(value):
        try:
            return f"{int(round(Decimal(value))):,}".replace(",", ".")
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            return "chưa cập nhật"

    def describe(service):
        duration = service.duration_minutes
        duration_text = f"{duration} phút" if duration else "chưa cập nhật thời lượng"
        return f"• {service.name} — {money(price_value(service))} đồng · {duration_text}"

    def service_list(title, rows):
        lines = [title]
        lines.extend(describe(service) for service in rows)
        return "\n".join(lines)

    def named_target():
        if exact_targets:
            return exact_targets[0]
        if len(contextual_targets) == 1:
            return contextual_targets[0]
        return None

    def parse_duration_minutes():
        numeric = re.search(r"\b(\d{1,3})\s*(phut|minutes?|mins?|gio|tieng|hours?|hrs?|h)\b", query)
        if numeric:
            value = int(numeric.group(1))
            return value * 60 if numeric.group(2) in {"gio", "tieng", "hour", "hours", "hr", "hrs", "h"} else value
        words = {
            "mot": 1, "one": 1, "hai": 2, "two": 2, "ba": 3, "three": 3,
            "bon": 4, "four": 4, "nam": 5, "five": 5,
        }
        word = re.search(r"\b(mot|one|hai|two|ba|three|bon|four|nam|five)\s*(tieng|gio|hours?)\b", query)
        return words[word.group(1)] * 60 if word else None

    def parse_price_amount():
        if not any(cue in query for cue in ("gia", "price", "cost", "chi phi", "bao nhieu tien")):
            return None
        pattern = re.compile(r"(?<!\w)(\d{1,3}(?:\s+\d{3})*|\d+)\s*(k|nghin|ngan|dong|vnd)?(?!\w)")
        for match in pattern.finditer(query):
            number = int(re.sub(r"\s+", "", match.group(1)))
            unit = match.group(2) or ""
            if unit in {"k", "nghin", "ngan"}:
                return Decimal(number * 1000)
            if unit in {"dong", "vnd"} or number >= 1000:
                return Decimal(number)
        return None

    target = named_target()
    asks_cheapest = any(cue in query for cue in (
        "gia thap nhat", "gia re nhat", "re nhat", "thap nhat", "cheapest", "lowest price",
    ))
    asks_price_table = any(cue in query for cue in (
        "bang gia", "tong hop", "tham khao gia", "so sanh gia", "price list", "compare prices",
    ))
    asks_duration_fit = any(cue in query for cue in (
        "phu hop", "chi co", "trong khoang", "toi da", "about", "around", "khoang", "within", "only have",
    )) and parse_duration_minutes() is not None
    asks_shorter = any(cue in query for cue in (
        "ngan hon", "thoi luong ngan", "shorter", "less time",
    ))
    asks_cheaper = any(cue in query for cue in (
        "gia thap hon", "re hon", "cheaper", "lower price", "it tien hon",
    ))
    amount = parse_price_amount()
    asks_price_filter = amount is not None and any(cue in query for cue in (
        "khoang", "tam", "duoi", "it hon", "thap hon", "around", "about", "under", "less than",
    ))
    asks_service_fact = any(cue in query for cue in (
        "gia", "bao nhieu", "bao lau", "thoi luong", "tim hieu", "chi phi", "bao gom", "phat sinh",
        "giai thich", "chi tiet", "mo ta", "price", "duration", "cost", "include", "included",
        "su dung", "tong chi phi", "vua gioi thieu", "ban dau",
    ))
    if not (asks_cheapest or asks_price_table or asks_duration_fit or asks_shorter or asks_cheaper or asks_price_filter or asks_service_fact):
        # A simple “shop có dịch vụ này không?” is still a service-catalog
        # question when it names a configured service. Generic capability
        # questions stay on the existing service-menu / knowledge route.
        if exact_targets:
            chosen = exact_targets[0]
            return f"Có ạ, {chosen.name} đang có trong danh mục dịch vụ của shop. {describe(chosen)}"
        return None

    ordered_services = sorted(services, key=lambda item: (price_value(item), item.name.casefold()))
    if asks_cheapest:
        lowest = min(price_value(service) for service in services)
        matches = [service for service in services if price_value(service) == lowest]
        return service_list("Dịch vụ có giá thấp nhất trong danh mục hiện tại:", matches)

    if asks_price_table:
        return service_list("Bảng giá dịch vụ hiện đang nhận lịch:", ordered_services)

    if asks_duration_fit:
        budget = parse_duration_minutes()
        # “khoảng một tiếng” means closest to 60 minutes; a hard upper bound
        # is used only when the customer explicitly says “tối đa/only”.
        hard_limit = any(cue in query for cue in ("toi da", "chi co", "only have", "within"))
        matches = [service for service in services if service.duration_minutes and (
            service.duration_minutes <= budget if hard_limit else abs(service.duration_minutes - budget) <= max(15, budget * 0.25)
        )]
        if matches:
            return service_list(f"Các dịch vụ phù hợp thời lượng khoảng {budget} phút:", sorted(matches, key=lambda item: (abs(item.duration_minutes - budget), price_value(item))))
        shortest = min(services, key=lambda item: item.duration_minutes or float("inf"))
        return f"Danh mục hiện chưa có dịch vụ phù hợp khoảng {budget} phút. Dịch vụ ngắn nhất là {shortest.name}, khoảng {shortest.duration_minutes} phút."

    if asks_price_filter and amount is not None:
        under = any(cue in query for cue in ("duoi", "it hon", "thap hon", "under", "less than"))
        tolerance = max(Decimal("30000"), amount * Decimal("0.10"))
        matches = [service for service in services if (
            price_value(service) <= amount if under else abs(price_value(service) - amount) <= tolerance
        )]
        if matches:
            label = f"không quá {money(amount)} đồng" if under else f"khoảng {money(amount)} đồng"
            return service_list(f"Các dịch vụ có giá {label}:", sorted(matches, key=lambda item: (abs(price_value(item) - amount), item.name.casefold())))
        return f"Mình chưa thấy dịch vụ nào có giá gần {money(amount)} đồng. {service_list('Bảng giá hiện có:', ordered_services)}"

    if asks_cheaper and target is not None:
        cheaper = [service for service in services if service.id != target.id and price_value(service) < price_value(target)]
        if not cheaper:
            return f"{target.name} hiện có giá {money(price_value(target))} đồng. Danh mục chưa có dịch vụ nào rẻ hơn để mình so sánh."
        lines = [f"Các dịch vụ có giá thấp hơn {target.name} ({money(price_value(target))} đồng):"]
        lines.extend(describe(service) for service in sorted(cheaper, key=lambda item: (price_value(item), item.name.casefold())))
        lines.append("Danh mục chưa đủ thông tin để khẳng định các dịch vụ này có nội dung tương tự.")
        return "\n".join(lines)

    if asks_shorter and target is not None:
        shorter = [service for service in services if service.id != target.id and service.duration_minutes and target.duration_minutes and service.duration_minutes < target.duration_minutes]
        if not shorter:
            return f"{target.name} cần khoảng {target.duration_minutes} phút. Danh mục hiện chưa có dịch vụ nào ngắn hơn để mình giới thiệu."
        lines = [f"Các dịch vụ có thời lượng ngắn hơn {target.name} ({target.duration_minutes} phút):"]
        lines.extend(describe(service) for service in sorted(shorter, key=lambda item: item.duration_minutes))
        lines.append("Danh mục chưa đủ thông tin để khẳng định các dịch vụ này có nội dung tương tự.")
        return "\n".join(lines)

    quantity = 1
    quantity_words = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5}
    quantity_match = re.search(r"\b(\d{1,2}|mot|hai|ba|bon|nam)\s*(?:lan|buoi|sessions?|times?)\b", query)
    if quantity_match:
        quantity = int(quantity_match.group(1)) if quantity_match.group(1).isdigit() else quantity_words[quantity_match.group(1)]
    if target is None:
        if len(contextual_targets) > 1 and has_followup_wording:
            return "Bạn đang hỏi dịch vụ nào trong các dịch vụ vừa nêu ạ? " + "; ".join(service.name for service in contextual_targets)
        if asks_cheaper:
            cheapest = [service for service in services if price_value(service) == min(price_value(item) for item in services)]
            return service_list("Dịch vụ có giá thấp nhất trong danh mục hiện tại:", cheapest)
        if has_service_wording:
            return service_list("Các dịch vụ shop đang nhận lịch:", ordered_services)
        return None

    if quantity > 1 and asks_service_fact:
        total = price_value(target) * quantity
        return (
            f"Theo giá trong danh mục, {quantity} lần sử dụng {target.name} dự kiến là "
            f"{money(total)} đồng ({quantity} × {money(price_value(target))} đồng/lần). "
            "Đây là mức tham khảo; chưa ghi nhận đặt lịch hay thanh toán."
        )

    details = [f"{target.name} có giá {money(price_value(target))} đồng/lần, thời lượng khoảng {target.duration_minutes} phút."]
    if any(cue in query for cue in ("giai thich", "chi tiet", "mo ta", "vua gioi thieu")):
        if target.description and target.description.strip():
            details.append(f"Mô tả từ shop: {target.description.strip()}")
        else:
            details.append("Danh mục hiện chưa có mô tả chi tiết hơn về dịch vụ này.")
    if any(cue in query for cue in ("bao gom", "toan bo chi phi", "chi phi phat sinh", "included", "include all")):
        details.append("Shop chưa cấu hình chi tiết các khoản phí kèm theo, nên mình chưa thể xác nhận giá đã bao gồm toàn bộ chi phí. Bạn nhắn nhân viên shop để xác nhận trước khi đặt nhé.")
    return " ".join(details)


def generic_recommendation_needs_question(text: str) -> str | None:
    """Do not rank products when a customer has not described their needs."""
    from app.services.product_resolver import normalize_product_text
    normalized = normalize_product_text(text)
    generic = re.search(r"\b(?:goi y|tu van)\b.*\bphu hop voi nhu cau\b", normalized)
    concrete = re.search(
        r"\b(?:da dau|da kho|da nhay cam|mun|duong am|ngan sach|duoi|tren|khoang|tam|"
        r"gia re|chong nang|mau hong|mau den)\b|\d", normalized)
    if generic and not concrete:
        return ("Bạn muốn mình gợi ý nhóm sản phẩm nào, cần đáp ứng nhu cầu gì "
                "và ngân sách khoảng bao nhiêu ạ? Mình sẽ dựa vào đó để chọn các món shop đang có.")
    return None
