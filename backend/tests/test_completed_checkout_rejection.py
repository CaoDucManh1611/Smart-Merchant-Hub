from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.sales import Order
from app.models.customer_collection import CustomerCollectionSession
from app.services.conversation_graph import graph_reply
from app.core.config import settings

@pytest.mark.parametrize('answer',['Không','Không nhé','Không mua nữa'])
def test_rejection_of_completed_collection_reaches_pending_invoice(setup,answer):
 db,c,p,*_=setup
 order=Order(business_id=1,customer_id=c.customer_id,conversation_id=c.id,order_number='CHAT-17',status='draft',total_amount=200000,paid_amount=0)
 db.add(order);db.flush()
 session=CustomerCollectionSession(business_id=1,customer_id=c.customer_id,conversation_id=c.id,source_channel=c.channel,purpose='order',status='completed',required_fields=['name','phone','email','address','payment_method'],collected_fields={'draft_order_id':order.id,'awaiting_customer_confirmation':True})
 db.add(session);db.commit()
 stock=(p.stock_quantity,p.reserved_quantity)
 with patch.object(settings,'CATALOG_DIALOGUE_ENABLED',True),patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('invoice rejection needs no AI')),patch('app.services.conversation_graph.call_llm',side_effect=AssertionError('invoice rejection needs no AI')):
  reply=graph_reply(db,business_id=1,conversation=c,query=answer,job_key='invoice-decline')
 assert 'chưa xác nhận' in reply.prompt
 assert session.status=='abandoned' and session.collected_fields['awaiting_customer_confirmation'] is False
 assert order.status=='draft' and order.metadata_['customer_confirmed'] is False
 assert (p.stock_quantity,p.reserved_quantity)==stock and order.paid_amount==0
 assert db.query(Order).count()==1
