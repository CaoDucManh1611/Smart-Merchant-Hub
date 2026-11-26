from unittest.mock import patch
from datetime import datetime,timedelta,timezone
from test_business_request import setup
from app.models.message import Message
from app.models.customer_collection import CustomerCollectionSession
from app.services.customer_collection_flow import advance_customer_collection,CollectionFlowResult
from app.services.conversation_turn_service import dispatch_chatbot_turn


def test_split_form_with_unreadable_card_asks_for_missing_phone(setup):
 db,c,p,*_=setup
 def turn(text):return advance_customer_collection(db,business_id=1,customer_id=c.customer_id,conversation_id=c.id,source_channel=c.channel,text=text)
 turn('Tôi muốn mua 3 Hàng thử')
 turn('xác nhận')
 for text in ['Khách Kiểm Tra','hoai@example.com','Bình Chánh']:
  turn(text)
 r=turn('Chuyển khoản')
 session=db.query(CustomerCollectionSession).filter_by(purpose='order').one()
 assert session.collected_fields['email']=='hoai@example.com'
 assert session.collected_fields['address']=='Bình Chánh'
 assert session.current_field=='phone'
 assert 'số điện thoại' in r.prompt and 'tin nhắn chữ' in r.prompt
 assert not session.collected_fields.get('draft_order_id')


def test_message_just_outside_debounce_is_not_dropped(setup):
 db,c,*_=setup
 now=datetime.now(timezone.utc).replace(tzinfo=None)
 first=Message(conversation_id=c.id,channel=c.channel,direction='inbound',sender_type='customer',content='hoai@example.com',received_at=now)
 second=Message(conversation_id=c.id,channel=c.channel,direction='inbound',sender_type='customer',content='Bình Chánh',received_at=now+timedelta(seconds=5.066))
 db.add_all([first,second]);db.commit()
 with patch('app.services.conversation_turn_service.settings.CONVERSATION_TURN_WAIT_SECONDS',5),patch('app.services.conversation_turn_service.settings.CHATBOT_GRAPH_ENABLED',True),patch('app.services.auto_reply_service.get_auto_reply_enabled',return_value=True),patch('app.services.privacy_service.customer_memory_opt_out_reply',return_value=None),patch('app.services.conversation_graph.graph_reply',return_value=CollectionFlowResult(session_id=1,status='partial',current_field='phone',prompt='')) as graph:
  dispatch_chatbot_turn(db,business_id=1,payload={'conversation_id':c.id,'message_id':first.id})
 graph.assert_called_once()
 assert graph.call_args.kwargs['query']=='hoai@example.com'


def test_complete_split_form_with_cod_reaches_invoice_without_ai(setup):
 from app.models.sales import Order
 from app.services.conversation_graph import graph_reply
 from app.core.config import settings
 db,c,p,*_=setup
 def turn(text):return advance_customer_collection(db,business_id=1,customer_id=c.customer_id,conversation_id=c.id,source_channel=c.channel,text=text)
 turn('Tôi muốn mua 3 Hàng thử');turn('xác nhận')
 with patch.object(settings,'CATALOG_DIALOGUE_ENABLED',True),patch('app.services.conversation_graph.call_llm',side_effect=AssertionError('no AI for checkout')),patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('no AI for checkout')):
  for index,text in enumerate(['Khách Kiểm Tra\n0900000011','hoai@example.com','Bình chánh','COd']):
   r=graph_reply(db,business_id=1,conversation=c,query=text,job_key=f'split-cod-{index}')
 assert r.prompt and 'CHAT-' in r.prompt
 session=db.query(CustomerCollectionSession).filter_by(purpose='order').one()
 assert session.collected_fields['email']=='hoai@example.com'
 assert session.collected_fields['address']=='Bình chánh'
 assert session.collected_fields['payment_method']=='cod'
 assert db.query(Order).count()==1
 assert db.query(Order).one().status=='draft'
