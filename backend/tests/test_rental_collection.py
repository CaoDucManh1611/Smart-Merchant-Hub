import pytest

@pytest.fixture(autouse=True)
def offline_interpretation():
    with patch('app.services.conversation_understanding.interpret_collection_turn', return_value=None):
        yield

from types import SimpleNamespace
from unittest.mock import patch
from app.services.rental_collection import advance_rental_request

class DB:
    def add(self, row):
        row.id = 9
        self.row = row
    def flush(self): pass
    def commit(self): pass


def test_rental_enquiry_collects_contact_and_notifies_without_creating_order():
    db = DB()
    room = SimpleNamespace(id=44, name="Phòng trọ 11", price=2000000,
        stock_quantity=1, reserved_quantity=0, metadata_={"offering_type": "rental"})
    args = dict(business_id=2, customer_id=4, conversation_id=5, source_channel="facebook")
    with patch('app.services.auto_reply_service._contextual_retrieval_query', return_value='Phòng trọ 11'), \
         patch('app.services.auto_reply_service._find_exact_product', return_value=(room, '')), \
         patch('app.services.rental_collection.create_rental_order', return_value=(SimpleNamespace(id=8, order_number='CHAT-9'), None)), \
         patch('app.services.customer_collection_flow.encrypt_contact', return_value='encrypted'), \
         patch('app.services.customer_collection_flow._store_contact') as contact, \
         patch('app.services.notification_service.create_notification') as notify:
        reply = advance_rental_request(db, **args, text='Ok cho tôi thuê phòng đó đi', session=None)
        assert 'Phòng trọ 11' in reply.prompt
        assert db.row.current_field == 'name'
        assert db.row.collected_fields['product_id'] == 44
        session = db.row
        advance_rental_request(db, **args, text='Nguyễn Văn A', session=session)
        assert session.current_field == 'phone'
        advance_rental_request(db, **args, text='sai số', session=session)
        assert session.current_field == 'phone'
        advance_rental_request(db, **args, text='0901234567', session=session)
        assert session.current_field == 'move_in'
        assert '0901234567' not in str(session.collected_fields)
        contact.assert_called_once()
        reply = advance_rental_request(db, **args, text='01/11/2026', session=session)
        assert session.status == 'completed'
        assert 'CHAT-9' in reply.prompt
        notify.assert_called_once()


def test_rental_unavailable_does_not_collect_or_reserve():
    db = DB()
    room = SimpleNamespace(id=44, name='Phòng trọ 11', stock_quantity=1, reserved_quantity=1,
        metadata_={'offering_type': 'rental'})
    with patch('app.services.auto_reply_service._contextual_retrieval_query', return_value='Phòng 11'), \
         patch('app.services.auto_reply_service._find_exact_product', return_value=(room, '')):
        reply = advance_rental_request(db, business_id=2, customer_id=4, conversation_id=5,
            source_channel='facebook', text='Tôi muốn thuê phòng 11', session=None)
    assert 'không còn khả dụng' in reply.prompt
    assert not hasattr(db, 'row')


def test_labeled_name_phone_and_date_are_collected_from_one_message():
    db = DB()
    session = SimpleNamespace(id=9, purpose="rental_request", status="pending", current_field="name",
        collected_fields={"product_id": 44, "product_name": "Phòng trọ 11"})
    with patch('app.services.rental_collection.create_rental_order', return_value=(SimpleNamespace(id=8, order_number='CHAT-9'), None)), \
         patch('app.services.customer_collection_flow.encrypt_contact', return_value='encrypted'), \
         patch('app.services.customer_collection_flow._store_contact') as contact, \
         patch('app.services.notification_service.create_notification') as notify:
        reply = advance_rental_request(db, business_id=2, customer_id=4, conversation_id=5,
            source_channel='facebook', session=session,
            text="Đức đã trả lời Đức\nHọ tên: Cao Đức Mạnh Sdt: 0901234567 Ngày vào: 01-11-2099\nĐây này")
    assert session.status == 'completed'
    assert session.collected_fields['name'] == 'Cao Đức Mạnh'
    assert session.collected_fields['move_in'] == '01-11-2099'
    contact.assert_called_once()
    notify.assert_called_once()

def test_past_move_in_date_keeps_contact_but_asks_for_new_date():
    db = DB()
    session = SimpleNamespace(id=9, purpose='rental_request', status='pending', current_field='name',
        collected_fields={'product_id': 44, 'product_name': 'Phòng trọ 11'})
    with patch('app.services.customer_collection_flow.encrypt_contact', return_value='encrypted'), \
         patch('app.services.customer_collection_flow._store_contact'), \
         patch('app.services.notification_service.create_notification') as notify:
        reply = advance_rental_request(db, business_id=2, customer_id=4, conversation_id=5,
            source_channel='facebook', session=session,
            text='Họ tên: Nguyễn Văn A Sdt: 0901234567 Ngày vào: 01-01-2000')
    assert session.current_field == 'move_in'
    assert session.collected_fields['name'] == 'Nguyễn Văn A'
    assert session.collected_fields['phone_collected']
    assert 'ngày' in reply.prompt
    notify.assert_not_called()

def test_rental_order_is_linked_once_and_reserves_inventory_until_confirmation():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database.bases import TenantBase
    from app.models import Business, Customer, Conversation
    from app.models.sales import Product, Order
    from app.models.customer_collection import CustomerCollectionSession
    from app.services.rental_collection import create_rental_order
    from app.services.order_service import transition_sales_order
    engine = create_engine('sqlite://')
    Business.metadata.create_all(engine)
    TenantBase.metadata.create_all(engine)
    with Session(engine, autoflush=False) as db:
        customer = Customer(business_id=2, name='Test renter', channel='facebook', external_user_id='renter')
        db.add(customer)
        db.flush()
        conversation = Conversation(business_id=2, customer_id=customer.id, channel='facebook')
        product = Product(business_id=2, name='Phòng trọ 11', sku='P11', price=2000000,
            stock_quantity=1, reserved_quantity=0, status='active', metadata_={'offering_type': 'rental'})
        db.add_all([conversation, product])
        db.flush()
        session = CustomerCollectionSession(business_id=2, customer_id=customer.id,
            conversation_id=conversation.id, purpose='rental_request', status='pending',
            source_channel='facebook', required_fields=[], collected_fields={
                'product_id': product.id, 'name': 'Nguyễn Văn A', 'move_in': '01/11/2099'})
        db.add(session)
        db.commit()
        session.collected_fields = {**session.collected_fields, "name": "Updated renter"}
        order, error = create_rental_order(db, session)
        assert order.metadata_["renter_name"] == "Updated renter"
        assert error is None
        db.commit()
        assert order.status == 'draft'
        assert order.total_amount == 2000000
        assert order.metadata_['move_in'] == '01/11/2099'
        from app.services.customer_order_service import customer_context_reply
        assert 'Updated renter' in customer_context_reply(db, 2, conversation.id, 'Tôi tên là gì bạn biết ko')
        assert 'Updated renter' in customer_context_reply(db, 2, conversation.id, 'Tôi hỏi bạn tên tôi là gì bạn biết ko')
        payment = customer_context_reply(db, 2, conversation.id, 'Cho tôi hỏi ko thanh toán hay j cả à')
        assert order.order_number in payment
        assert 'chờ nhân viên xác nhận' in payment
        assert 'chờ nhân viên xác nhận' in customer_context_reply(db, 2, conversation.id,
            f'Gửi QR chuyển khoản đơn {order.order_number} cho tôi nhé')
        assert 'chưa tìm thấy' in customer_context_reply(db, 2, conversation.id,
            'Gửi QR chuyển khoản đơn TEST-NOTFOUND nhé')
        assert 'thiếu' not in customer_context_reply(db, 2, conversation.id, 'Bạn nhận đc thông tin của tôi chưa')
        other = Customer(business_id=2, name='Other customer', channel='facebook', external_user_id='other')
        db.add(other)
        db.flush()
        other_conversation = Conversation(business_id=2, customer_id=other.id, channel='facebook')
        db.add(other_conversation)
        db.commit()
        assert 'Updated renter' not in customer_context_reply(db, 2, other_conversation.id, 'Tên tôi là gì')

        assert product.reserved_quantity == 1
        again, error = create_rental_order(db, session)
        assert again.id == order.id
        assert db.query(Order).count() == 1
        assert product.reserved_quantity == 1
        confirmed = transition_sales_order(db, order_id=order.id, to_status='confirmed', actor_id=None, business_id=2)
        db.commit()
        assert confirmed.status == 'confirmed'
        assert product.reserved_quantity == 1
        transition_sales_order(db, order_id=order.id, to_status='cancelled', actor_id=None, business_id=2)
        db.commit()
        assert product.reserved_quantity == 0



def test_llm_understands_unlabelled_date_and_keeps_existing_identity():
    db = DB()
    session = SimpleNamespace(id=9, purpose='rental_request', status='pending', current_field='move_in',
        collected_fields={'product_id':44, 'product_name':'Phòng trọ 02', 'name':'Cao Đức Mạnh', 'phone_collected':True})
    with patch('app.services.conversation_understanding.interpret_collection_turn', return_value={
        'intent':'provide_information', 'fields':{'move_in':'26/11/2099'}}), \
         patch('app.services.rental_collection.create_rental_order', return_value=(SimpleNamespace(id=8,order_number='CHAT-9'),None)), \
         patch('app.services.notification_service.create_notification'):
        reply=advance_rental_request(db,business_id=2,customer_id=4,conversation_id=5,
            source_channel='facebook',text='Ngày 26/11/2099',session=session)
    assert session.status=='completed'
    assert session.collected_fields['name']=='Cao Đức Mạnh'
    assert 'CHAT-9' in reply.prompt


def test_question_during_collection_is_not_saved_as_a_name():
    db=DB()
    session=SimpleNamespace(id=9,purpose='rental_request',status='pending',current_field='name',collected_fields={})
    with patch('app.services.conversation_understanding.interpret_collection_turn',return_value={'intent':'question','fields':{}}):
        assert advance_rental_request(db,business_id=2,customer_id=4,conversation_id=5,
            source_channel='facebook',text='Phòng có wifi không?',session=session) is None
    assert session.collected_fields=={}


def test_unrelated_turn_cannot_create_order_from_previously_complete_fields():
    session=SimpleNamespace(id=9,purpose='rental_request',status='partial',current_field=None,
        collected_fields={'product_id':44,'product_name':'Room A','name':'Test Customer',
                          'phone_collected':True,'move_in':'01/11/2099'})
    with patch('app.services.conversation_understanding.interpret_collection_turn',return_value={'intent':'provide_information','fields':{}}), \
         patch('app.services.rental_collection.create_rental_order') as create:
        assert advance_rental_request(DB(),business_id=2,customer_id=4,conversation_id=5,
            source_channel='facebook',text='Gửi QR cho tôi',session=session) is None
    create.assert_not_called()
