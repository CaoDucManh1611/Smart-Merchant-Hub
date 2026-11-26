from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.sales import Product,Order
from app.models.message import Message
from app.models.customer_collection import CustomerCollectionSession
from app.services.conversation_graph import graph_reply
from app.core.config import settings

@pytest.mark.parametrize('with_history',[False,True])
def test_named_purchase_does_not_need_catalog_interpreter(setup,with_history):
 db,c,old,*_=setup
 lip=Product(business_id=1,sku='LIP-CLEAR',name='Son dưỡng môi không màu 4g',price=59000,stock_quantity=47,status='active')
 db.add(lip);db.flush()
 if with_history:
  db.add(Message(conversation_id=c.id,channel=c.channel,direction='outbound',sender_type='bot',status='sent',content='Son dưỡng môi không màu 4g: 59.000 đồng/sản phẩm; còn 47 sản phẩm.',metadata_={'catalog_dialogue':{'intent':'detail','shortlist':[lip.id]}}))
 db.commit()
 with patch.object(settings,'CATALOG_DIALOGUE_ENABLED',True),patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('named purchase needs no AI')),patch('app.services.conversation_graph.call_llm',side_effect=AssertionError('checkout needs no AI')):
  result=graph_reply(db,business_id=1,conversation=c,query='Tôi muốn mua 2 son dưỡng môi không màu',job_key='named-lip')
 assert '118.000' in result.prompt and 'Son dưỡng môi không màu' in result.prompt
 session=db.query(CustomerCollectionSession).one()
 assert session.collected_fields['items'][0]['product_id']==lip.id
 assert session.collected_fields['items'][0]['quantity']==2
 assert db.query(Order).count()==0
