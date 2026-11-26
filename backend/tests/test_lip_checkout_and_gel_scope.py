from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.sales import Product
from app.models.message import Message
from app.models.customer_collection import CustomerCollectionSession
from app.services.catalog_dialogue import catalog_dialogue_reply
from app.services.customer_collection_flow import advance_customer_collection


def catalog(db):
 rows=[]
 for sku,name,category,price in [
 ('LIP','Son dưỡng môi không màu 4g','Son dưỡng môi',59000),
 ('LIP-NIGHT','Son dưỡng môi dùng ban đêm 8g','Son dưỡng môi',99000),
 ('MOIST-DAY','Gel dưỡng ẩm ban ngày 30g','Kem dưỡng dạng gel',119000),
 ('MOIST-NIGHT','Gel dưỡng ẩm ban đêm 50g','Kem dưỡng dạng gel',179000),
 ('WASH','Gel rửa mặt tạo bọt 200ml','Gel rửa mặt',169000)]:
  p=Product(business_id=1,sku=sku,name=name,price=price,stock_quantity=48,status='active',metadata_={'product_profile':{'category':category,'benefits':['Công dụng của shop']}})
  db.add(p);rows.append(p)
 db.commit();return rows


def test_gel_moisturizer_group_never_substitutes_face_wash(setup):
 db,c,*_=setup;catalog(db)
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('must ground group from names')):
  r=catalog_dialogue_reply(db,1,c,'Các loại gel dưỡng ẩm có trong shop')
 assert 'Gel dưỡng ẩm ban ngày' in r.prompt and 'Gel dưỡng ẩm ban đêm' in r.prompt
 assert 'Gel rửa mặt' not in r.prompt


def test_distinct_lip_name_allows_one_omitted_internal_word(setup):
 db,c,*_=setup;catalog(db)
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('must ground unique name')):
  r=catalog_dialogue_reply(db,1,c,'Tôi muốn xem chi tiết son môi không màu')
 assert 'Son dưỡng môi không màu' in r.prompt and 'Công dụng:' in r.prompt
 assert 'ban đêm' not in r.prompt


def test_counted_purchase_references_latest_lip_then_changes_to_two(setup):
 db,c,old,*_=setup;lip,*_=catalog(db)
 old.name='Mặt nạ đất sét làm sạch 30g';old.price=79000
 db.add(Message(conversation_id=c.id,channel=c.channel,direction='outbound',sender_type='bot',content=f'{old.name}: 79.000 đồng.'))
 db.add(Message(conversation_id=c.id,channel=c.channel,direction='outbound',sender_type='bot',content=f'{lip.name}: 59.000 đồng/sản phẩm.',metadata_={'catalog_dialogue':{'intent':'detail','group':'Son dưỡng môi','shortlist':[lip.id]}}));db.commit()
 r=advance_customer_collection(db,business_id=1,customer_id=c.customer_id,conversation_id=c.id,source_channel=c.channel,text='Ok cho tôi đặt 1 cái nha')
 assert 'Son dưỡng môi không màu' in r.prompt and '59.000' in r.prompt
 assert 'Mặt nạ' not in r.prompt
 r=advance_customer_collection(db,business_id=1,customer_id=c.customer_id,conversation_id=c.id,source_channel=c.channel,text='Tôi muốn mua 2 cái đi')
 assert 'Son dưỡng môi không màu' in r.prompt and '118.000' in r.prompt
 session=db.query(CustomerCollectionSession).filter_by(id=r.session_id).one()
 assert session.collected_fields['items'][0]['quantity']==2
 assert session.collected_fields['items'][0]['product_id']==lip.id


def test_full_graph_counted_reference_never_calls_ai_or_selects_mask(setup):
 from app.core.config import settings
 from app.services.conversation_graph import graph_reply
 db,c,mask,*_=setup;lip,*_=catalog(db)
 mask.name='Mặt nạ đất sét làm sạch 30g'
 db.add(Message(conversation_id=c.id,channel=c.channel,direction='outbound',sender_type='bot',content=f'{lip.name}: 59.000 đồng/sản phẩm.',metadata_={'catalog_dialogue':{'intent':'detail','group':'Son dưỡng môi','shortlist':[lip.id]}}));db.commit()
 with patch.object(settings,'CATALOG_DIALOGUE_ENABLED',True),patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('no remote call for counted reference')):
  r=graph_reply(db,business_id=1,conversation=c,query='Ok cho tôi đặt 1 cái nha',job_key='lip-counted-ref')
  assert 'Son dưỡng môi không màu' in r.prompt and 'Mặt nạ' not in r.prompt
  r=graph_reply(db,business_id=1,conversation=c,query='Tôi muốn mua 2 cái đi',job_key='lip-counted-update')
  assert '118.000' in r.prompt and 'Son dưỡng môi không màu' in r.prompt


def test_reference_without_any_subject_does_not_guess_a_product(setup):
 from app.services.product_resolver import resolve_product_mentions
 db,c,mask,*_=setup;catalog(db);mask.name='Mặt nạ đất sét làm sạch 30g';db.commit()
 assert resolve_product_mentions(db,business_id=1,conversation_id=c.id,text='Ok cho tôi đặt 1 cái nha')==[]
