"""Read-only arithmetic for a single offering in an open customer request."""
import re
from decimal import Decimal
from app.rag.topics import fold_topic_text
from app.services.catalog_search import get_current_offering
from app.services.business_profile import get_business_profile


def pending_quantity_quote(db, business_id, query, session):
    if session is None or session.business_id != business_id or session.purpose != "business_request":
        return None
    folded = fold_topic_text(query)
    if not any(term in folded for term in ("bao nhieu", "tong tien", "thanh tien", "hoa don", "can tra")):
        return None
    # Discount/policy, multi-product and delivery-fee questions require their
    # own sources; do not turn them into a base-price promise.
    if any(term in folded for term in ("giam", "khuyen mai", "phi ship", "van chuyen", "combo", "va ")):
        return None
    matches = re.findall(r"\b(?:mua|lay|dat|so luong)\s+(\d{1,5})\b|\b(\d{1,5})\s*(?:san pham|chai|cai|hop|chiec|bo)\b", folded)
    quantities = {int(left or right) for left, right in matches}
    fields = session.collected_fields or {}
    if not quantities and any(term in folded for term in ("tong", "hoa don", "can tra")):
        quantity = (fields.get("values") or {}).get("quantity")
        if str(quantity).isdigit():
            quantities = {int(quantity)}
    if len(quantities) != 1:
        return None
    quantity = next(iter(quantities))
    if not 1 <= quantity <= 10000:
        return None
    profile = get_business_profile(db, business_id)
    offering = get_current_offering(db, business_id, fields.get("offering_ref"), profile)
    if offering is None or offering["kind"] != "goods":
        return None
    # Only generic references or the selected name/SKU may use pending identity.
    remainder = re.sub(r"\b\d+\b", " ", folded)
    name = fold_topic_text(offering["name"])
    sku = fold_topic_text(offering.get("sku", ""))
    remainder = remainder.replace(name, " ")
    if sku:
        remainder = remainder.replace(sku, " ")
    allowed = set("neu toi minh em anh chi muon mua lay dat so luong san pham chai cai hop chiec bo nay do tren thi gia bao nhieu tien tong thanh hoa don can tra la het cho shop cua mot voi a nhe duoc khong".split())
    if any(token not in allowed for token in remainder.split()):
        return None
    price = Decimal(offering["price"])
    subtotal = price * quantity
    money = lambda amount: f"{amount:,.0f}".replace(",", ".")
    lines = [f"{offering['name']}: {money(price)} đồng/sản phẩm.",
             f"{quantity} × {money(price)} = {money(subtotal)} đồng tiền hàng."]
    policy = profile.payment_policies["goods"]
    if policy.mode == "order_total":
        charges = sum((line.amount for line in policy.fixed_charges), Decimal(0))
        lines.extend(f"{line.label}: {money(line.amount)} đồng." for line in policy.fixed_charges)
        lines.append(f"Tổng theo cấu hình hiện tại: {money(subtotal + charges)} đồng.")
    else:
        lines.append("Tổng khoản thu cuối cùng cần shop xác nhận theo bảng kê.")
    lines.append("Khoản phát sinh ngoài bảng kê (nếu có) cần shop xác nhận; đây chưa phải xác nhận tạo đơn hay đã thanh toán.")
    if quantity > offering["available"]:
        lines.append(f"Hiện chỉ còn {offering['available']} sản phẩm khả dụng, chưa đủ số lượng bạn hỏi.")
    return "\n".join(lines)
