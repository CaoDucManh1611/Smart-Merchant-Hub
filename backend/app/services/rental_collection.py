"""Collect rental enquiries and link them to staff-reviewed sales drafts."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo


def advance_rental_request(db, *, business_id, customer_id, conversation_id, source_channel, text, session):
    from app.services.customer_collection_flow import (
        CollectionFlowResult, _fold, _extract_value, _store_contact, _format_vnd,
        _is_checkout_cancel_request, _parse_order_form_details, encrypt_contact,
    )
    from app.models.customer_collection import CustomerCollectionSession
    from app.services.auto_reply_service import (
        _contextual_retrieval_query, _find_exact_product, _is_rental_room,
    )
    from app.services.notification_service import create_notification

    active = session is not None and session.purpose == "rental_request"
    folded = _fold(text)
    wants_rental = bool(re.search(r"\b(?:muon thue|cho (?:toi|minh) thue|dat thue|dat phong|thue phong|want to rent)\b", folded))
    if not active and not wants_rental:
        return None

    def result(prompt):
        return CollectionFlowResult(session_id=session.id if session else 0,
            status=session.status if session else "product_clarification",
            current_field=session.current_field if session else None, prompt=prompt, started=not active)

    if active and _is_checkout_cancel_request(text):
        session.status = "cancelled"
        db.commit()
        return result("Mình đã dừng thu thập yêu cầu thuê. Chưa có phòng nào được giữ hoặc đặt.")
    if not active:
        query = _contextual_retrieval_query(db, business_id, text, conversation_id) if conversation_id else text
        product, _ = _find_exact_product(db, business_id, query)
        if product is None:
            return result("Bạn muốn thuê phòng hoặc tài sản nào? Gửi mình tên hoặc mã để kiểm tra nhé.")
        if not _is_rental_room(product):
            return None
        if max(int(product.stock_quantity or 0) - int(product.reserved_quantity or 0), 0) < 1:
            return result(f"{product.name} hiện không còn khả dụng. Bạn muốn xem lựa chọn khác không?")
        if session is not None:
            return result("Bạn đang có yêu cầu khác chưa hoàn tất. Bạn muốn hủy yêu cầu đó trước khi đăng ký thuê không?")
        session = CustomerCollectionSession(business_id=business_id, customer_id=customer_id,
            conversation_id=conversation_id, source_channel=source_channel, purpose="rental_request",
            required_fields=["name", "phone", "move_in"], current_field="name", status="pending",
            collected_fields={"product_id": product.id, "product_name": product.name})
        db.add(session)
        db.flush()
        db.commit()
        return result(f"Bạn muốn đăng ký thuê {product.name}, giá hiện tại {_format_vnd(product.price)} đồng/tháng. "
            "Mình xin họ tên của bạn trước nhé. Sau đó mình sẽ hỏi số liên hệ và ngày dự kiến vào. "
            "Đây là yêu cầu thuê, chưa phải xác nhận giữ phòng.")

    fields = dict(session.collected_fields or {})
    field = session.current_field
    prompts = {"name": "Bạn cho mình họ tên nhé.", "phone": "Bạn cho mình số điện thoại liên hệ nhé.",
        "move_in": "Bạn dự kiến vào ở ngày nào? Bạn có thể ghi ngày/tháng/năm nhé."}
    from app.services.conversation_understanding import interpret_collection_turn
    understanding = interpret_collection_turn(text, required_fields=["name", "phone", "move_in"],
        current_field=field, collected_fields=fields)
    if understanding is None:
        values, _, _ = _parse_order_form_details(text, ["name", "phone", "move_in"], fallback_field=field)
    else:
        values = understanding["fields"]
        if understanding["intent"] == "question" and not values:
            return None

    if wants_rental:
        values = {}
    if not values:
        return None
    for key, value in values.items():
        if key == "name" and (len(value.split()) < 2 or any(char.isdigit() for char in value)
                or "?" in value or re.search(r"\b(?:ban can|hoi.*them|day nay)\b", _fold(value))):
            continue
        if key == "move_in" and not re.search(r"\d|mai|hom nay|tuan|thang|tomorrow|today|week|month", _fold(value)):
            continue
        if key == "move_in":
            date_match = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", value)
            if not date_match:
                continue
            if date_match:
                try:
                    day, month, year = map(int, date_match.groups())
                    if datetime(year, month, day).date() < datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date():
                        continue
                except ValueError:
                    continue
        if key == "phone":
            value = _extract_value("phone", value)
            if not value:
                continue
            _store_contact(db, business_id=business_id, customer_id=customer_id, kind="phone", value=value)
            fields["phone_collected"] = True
            fields["encrypted_phone"] = encrypt_contact("phone", value)
        else:
            fields[key] = value
    session.collected_fields = fields
    next_field = next((key for key in ("name", "phone", "move_in")
        if not fields.get("phone_collected" if key == "phone" else key)), None)
    session.current_field = next_field
    if next_field:
        db.commit()
        return result(prompts[next_field])
    order, error = create_rental_order(db, session)
    if order is None:
        session.status = "partial"
        session.current_field = "move_in"
        db.commit()
        return result(f"Thông tin của bạn đã được lưu nhưng chưa tạo được đơn thuê: {error}")
    session.status = "completed"
    create_notification(db, business_id=business_id, kind="rental_request",
        title="Khách đăng ký thuê", body=f"Đơn {order.order_number}: yêu cầu thuê {fields['product_name']}, chờ nhân viên xác nhận trong Đơn bán.",
        metadata={"conversation_id": conversation_id, "customer_id": customer_id, "order_id": order.id,
            "product_id": fields["product_id"], "collection_session_id": session.id})
    db.commit()
    return result(f"Mình đã tạo đơn thuê {order.order_number} cho {fields['product_name']}, đang chờ nhân viên xác nhận. "
        "Bạn chưa được xác nhận đặt thành công; nhân viên sẽ kiểm tra lịch vào và thủ tục.")


def create_rental_order(db, session):
    from app.models.customer_collection import CustomerCollectionSession, CustomerContact
    from app.models.sales import Product
    from app.services.customer_collection_flow import _create_draft_order_for_session, decrypt_contact
    db.flush()
    # Serialize retries for one request before checking its existing draft link.
    session = db.query(CustomerCollectionSession).filter(
        CustomerCollectionSession.id == session.id,
        CustomerCollectionSession.business_id == session.business_id,
    ).with_for_update().populate_existing().one()
    fields = dict(session.collected_fields or {})
    product = db.query(Product).filter(Product.business_id == session.business_id,
        Product.id == fields.get("product_id"), Product.status == "active").first()
    if product is None:
        return None, "Phòng hoặc tài sản đã ngừng cung cấp, cần nhân viên kiểm tra."
    if not fields.get("draft_order_id"):
        fields.update(quantity=1, unit_price=str(product.price))
        session.collected_fields = fields
    order, error = _create_draft_order_for_session(db, session=session)
    if order is None:
        return None, error
    metadata = dict(order.metadata_ or {})
    metadata.update(offering_type="rental", move_in=fields.get("move_in"),
        renter_name=fields.get("name"), billing_unit="tháng", invoice_confirmation_status="awaiting_staff")
    order.metadata_ = metadata
    if fields.get("encrypted_phone"):
        order.shipping_phone = decrypt_contact("phone", fields["encrypted_phone"])
    elif fields.get("phone_collected"):
        contact = db.query(CustomerContact).filter(
            CustomerContact.business_id == session.business_id,
            CustomerContact.customer_id == session.customer_id,
            CustomerContact.kind == "phone", CustomerContact.is_primary.is_(True),
        ).order_by(CustomerContact.id.desc()).first()
        if contact is not None:
            order.shipping_phone = decrypt_contact("phone", contact.value_encrypted)
    db.flush()
    return order, None
