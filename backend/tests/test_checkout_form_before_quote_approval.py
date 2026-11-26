from unittest.mock import patch
from test_business_request import setup
from app.models.sales import Order
from app.models.customer_collection import CustomerCollectionSession
from app.services.conversation_graph import graph_reply
from app.core.config import settings


def test_complete_form_after_quote_is_consumed_without_retyping_or_final_approval(setup):
 db,c,p,*_=setup;p.name='Kem dưỡng mềm da hằng ngày 30g';p.price=129000;p.stock_quantity=19;db.commit()
 with patch.object(settings,'CATALOG_DIALOGUE_ENABLED',True),patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('no AI')),patch('app.services.conversation_graph.call_llm',side_effect=AssertionError('no AI')):
  r=graph_reply(db,business_id=1,conversation=c,query='Tôi muốn mua 3 Kem dưỡng mềm da hằng ngày 30g',job_key='before-form-quote')
  assert '387.000' in r.prompt
  r=graph_reply(db,business_id=1,conversation=c,query='Khách Kiểm Tra\n0900000011\nhoai@example.com\nBình Chánh\nCOD',job_key='before-form-details')
 session=db.query(CustomerCollectionSession).one()
 assert session.purpose=='order' and session.collected_fields['name']=='Khách Kiểm Tra'
 assert session.collected_fields['email']=='hoai@example.com' and session.collected_fields['address']=='Bình Chánh'
 assert session.collected_fields['payment_method']=='cod'
 order=db.query(Order).one()
 assert order.status=='draft' and order.paid_amount==0 and order.total_amount==387000
 assert session.collected_fields['awaiting_customer_confirmation'] is True
 assert 'CHAT-' in r.prompt and r.prompt!='Bạn xác nhận đặt hàng chứ?'
