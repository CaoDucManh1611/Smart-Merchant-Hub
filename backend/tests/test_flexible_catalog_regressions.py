from unittest.mock import patch
from test_business_request import setup
from app.models.sales import Product,Order
from app.models.message import Message
from app.models.customer_collection import CustomerCollectionSession
from app.services.catalog_dialogue import catalog_dialogue_reply
from app.services.conversation_graph import graph_reply
from app.core.config import settings


def test_purchase_prefix_never_becomes_clay_product_identity(setup):
 from app.services.product_resolver import resolve_product_mentions
 db,c,mask,*_=setup;mask.name='Mặt nạ đất sét làm sạch 30g';mask.price=79000
 serum=Product(business_id=1,sku='SER-NIGHT',name='Serum dưỡng da ban đêm 30ml',price=229000,stock_quantity=23,status='active')
 other=Product(business_id=1,sku='CREAM-NIGHT',name='Kem dưỡng da ban đêm 50g',price=199000,stock_quantity=12,status='active')
 db.add_all([serum,other]);db.flush()
 db.add(Message(conversation_id=c.id,channel=c.channel,direction='outbound',sender_type='bot',status='sent',content=f'{serum.name}: 229.000 đồng.',metadata_={'catalog_dialogue':{'intent':'detail','shortlist':[serum.id]}}));db.commit()
 query='Ok cho tôi đặt 3 đơn serum dưỡng da ban đêm đi'
 assert [p.id for p in resolve_product_mentions(db,business_id=1,text=query,conversation_id=None)]==[serum.id]
 with patch.object(settings,'CATALOG_DIALOGUE_ENABLED',True),patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('no AI')),patch('app.services.conversation_graph.call_llm',side_effect=AssertionError('no AI')):
  reply=graph_reply(db,business_id=1,conversation=c,query=query,job_key='serum-prefix')
 assert 'Serum dưỡng da ban đêm' in reply.prompt and '687.000' in reply.prompt
 assert 'Mặt nạ' not in reply.prompt
 session=db.query(CustomerCollectionSession).one()
 assert session.collected_fields['items'][0]['product_id']==serum.id and session.collected_fields['items'][0]['quantity']==3
 assert db.query(Order).count()==0


def test_price_filter_accepts_natural_polite_tail_without_ai(setup):
 db,c,p,*_=setup;p.price=229000;p.name='Serum dưỡng da';db.commit()
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('no AI')):
  r=catalog_dialogue_reply(db,1,c,'Tôi muốn tìm sản phẩm nào trên 200k là đc')
 assert p.id in r.metadata['catalog_dialogue']['shortlist']


def test_unavailable_category_is_shop_question_not_scope_refusal(setup):
 db,c,p,*_=setup;p.name='Serum dưỡng da';db.commit()
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('no AI')):
  r=catalog_dialogue_reply(db,1,c,'Không biết ở đây ngoài mỹ phẩm ra thì có bán quần áo ko')
 assert 'chưa có quần áo' in r.prompt and r.status=='catalog_dialogue'
 clothing=Product(business_id=1,sku='SHIRT',name='Quần áo thể thao',price=200000,stock_quantity=2,status='active');db.add(clothing);db.commit()
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('no AI')):
  r=catalog_dialogue_reply(db,1,c,'Shop có bán quần áo ko')
 assert 'Quần áo thể thao' in r.prompt and clothing.id in r.metadata['catalog_dialogue']['shortlist']


def test_literal_soil_product_name_is_not_stripped_as_purchase_verb(setup):
 from app.services.product_resolver import find_explicit_product_mentions
 db,c,p,*_=setup;p.name='Đất trồng cây hữu cơ';p.sku='SOIL';db.commit()
 assert [row.id for row in find_explicit_product_mentions([p],'Đất trồng cây hữu cơ')]==[p.id]
 assert [row.id for row in find_explicit_product_mentions([p],'Cho tôi đặt 2 đất trồng cây hữu cơ')]==[p.id]
