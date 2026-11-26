"""Collect an explicit order number, then hand returns to staff without refunding."""
import re
from datetime import datetime, timezone
from app.rag.topics import fold_topic_text
from app.models.conversation import Conversation
from app.models.customer_collection import CustomerCollectionSession
from app.models.sales import Order

ACK = "Hiện tại shop đã nhận thông tin hoàn đơn {number} của bạn. Xin vui lòng đợi nhân viên hỗ trợ vấn đề của mình nhé."


def return_intent(text):
    folded=fold_topic_text(text)
    if any(term in folded for term in ('chinh sach','dieu kien','co duoc','duoc khong','can i return','eligible')):
        return False
    if re.search(r'\b(?:khong|chua) (?:muon|can|yeu cau)?\s*(?:hoan|tra)\b',folded):
        return False
    return bool(re.search(r'\b(?:hoan(?: lai)? (?:don|hang|tien)|tra (?:lai )?hang|refund my order|i want a refund|i need a refund)\b',folded))


def customer_return_reply(db,business_id,conversation_id,text,*,platform_db=None):
    from app.services.customer_order_service import extract_order_number, request_order_refund
    from app.models.notification import Notification
    from app.services.notification_service import create_notification
    conversation=db.query(Conversation).filter(Conversation.id==conversation_id,
        Conversation.business_id==business_id).with_for_update().first()
    if conversation is None:
        return None
    session=db.query(CustomerCollectionSession).filter(
        CustomerCollectionSession.business_id==business_id,
        CustomerCollectionSession.conversation_id==conversation_id,
        CustomerCollectionSession.customer_id==conversation.customer_id,
        CustomerCollectionSession.purpose=='order_return',
    ).order_by(CustomerCollectionSession.id.desc()).first()
    requested=return_intent(text)
    number=extract_order_number(text)
    bare_number=bool(number and re.fullmatch(r'\s*(?:(?:mã\s+)?đơn(?:\s+hàng)?\s*[:#]?\s*)?'+re.escape(number)+r'\s*[.!]?\s*',text,re.I))
    if not requested and not (session and session.status=='pending') and not (session and bare_number):
        return None
    if not requested and not bare_number and session and session.status=='completed':
        return None
    if session is None or (requested and session.status=='completed'):
        session=CustomerCollectionSession(business_id=business_id,customer_id=conversation.customer_id,
            conversation_id=conversation_id,purpose='order_return',source_channel=conversation.channel,
            required_fields=['order_number'],current_field='order_number',status='pending',
            collected_fields={'reason':text[:500]})
        db.add(session)
    if not number:
        db.commit()
        return 'Bạn vui lòng gửi mã đơn hàng muốn hoàn (ví dụ CHAT-14) để shop tiếp nhận và chuyển nhân viên hỗ trợ nhé.'
    order=db.query(Order).filter(Order.business_id==business_id,Order.customer_id==conversation.customer_id,
        Order.order_number==number).first()
    if order is None:
        db.commit()
        return 'Mình chưa tìm thấy mã đơn này thuộc tài khoản của bạn. Bạn kiểm tra và gửi lại mã đơn cần hoàn nhé.'
    if session.status=='completed' and (session.collected_fields or {}).get('order_number')==number:
        db.commit()
        return ACK.format(number=number)
    result=request_order_refund(db,business_id,conversation_id,
        {'order_number':number,'reason':(session.collected_fields or {}).get('reason') or text[:500]},platform_db=platform_db)
    if not result.get('accepted'):
        db.commit()
        return 'Shop chưa ghi nhận được yêu cầu hoàn đơn này. Bạn vui lòng liên hệ nhân viên để kiểm tra thêm nhé.'
    key=f'order-return:{conversation_id}:{order.id}:staff-review'
    if db.query(Notification).filter(Notification.business_id==business_id,Notification.idempotency_key==key).first() is None:
        create_notification(db,business_id=business_id,kind='order_return',title=f'Khách yêu cầu hoàn đơn {number}',
            body='Đã nhận mã đơn từ khách; cần nhân viên liên hệ và xem xét. Chưa hoàn tiền hoặc đổi trạng thái đơn.',
            metadata={'order_id':order.id,'conversation_id':conversation_id,'ticket_id':result['ticket_id']},idempotency_key=key)
    session.status='completed';session.current_field=None
    session.completed_at=datetime.now(timezone.utc).replace(tzinfo=None)
    session.collected_fields={**(session.collected_fields or {}),'order_number':number,'ticket_id':result['ticket_id']}
    db.commit()
    return ACK.format(number=number)
