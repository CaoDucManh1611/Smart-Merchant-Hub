from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.sales import Product
from app.models.message import Message
from app.services.catalog_dialogue import catalog_dialogue_reply
from app.services.customer_collection_flow import advance_customer_collection
from app.services.universal_sales_brain import resolve_industry_profiles,TenantIndustryConfig,discover_needs


def test_copied_product_price_does_not_break_stock_lookup(setup):
 db,c,p,*_=setup;p.name='Dầu gội làm sạch hằng ngày 250ml';p.price=109000;p.stock_quantity=30;p.reserved_quantity=0;p.metadata_={'product_profile':{'category':'Dầu gội'}};db.commit()
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('stock must not need AI')):
  r=catalog_dialogue_reply(db,1,c,'tôi muốn mua Dầu gội làm sạch hằng ngày 250ml — 109.000 đồng, shop còn bao nhiêu hàng')
 assert '30' in r.prompt and 'có thể bán' in r.prompt and 'size' not in r.prompt


def test_generic_place_order_keeps_latest_shampoo_and_asks_quantity(setup):
 db,c,mask,*_=setup;mask.name='Mặt nạ đất sét làm sạch 30g'
 p=Product(business_id=1,sku='SHAMPOO',name='Dầu gội làm sạch hằng ngày 250ml',price=109000,stock_quantity=30,status='active');db.add(p);db.flush()
 db.add(Message(conversation_id=c.id,channel=c.channel,direction='outbound',sender_type='bot',content=f'{p.name}: hiện còn 30 sản phẩm.',metadata_={'catalog_dialogue':{'intent':'detail','group':'Dầu gội','shortlist':[p.id]}}));db.commit()
 r=advance_customer_collection(db,business_id=1,customer_id=c.customer_id,conversation_id=c.id,source_channel=c.channel,text='tôi muốn đặt hàng')
 assert r.current_field=='quantity' and 'Dầu gội' in r.prompt
 assert 'Mặt nạ' not in r.prompt


def test_fashion_size_trigger_never_matches_ao_inside_bao():
 context=resolve_industry_profiles(1,TenantIndustryConfig(business_id=1,industry_ids=('fashion_apparel',)))
 r=discover_needs('tôi muốn mua dầu gội, shop còn bao nhiêu hàng',context)
 assert 'size' not in r.missing_slots
 positive=discover_needs('tôi muốn mua áo thun',context)
 assert 'size' in positive.missing_slots


def test_unknown_hair_need_shows_grounded_options_without_claiming_suitability(setup):
 db,c,p,*_=setup;p.name='Dầu gội làm sạch hằng ngày 250ml';p.price=109000;p.metadata_={'product_profile':{'category':'Dầu gội','benefits':['Làm sạch tóc và da đầu'],'suitable_needs':['gội đầu']}};db.commit()
 slots=dict(intent='recommend',domain='products',group='Dầu gội',product=None,budget=200000,need='tóc bết',reference=True,confidence=.99)
 with patch('app.services.catalog_dialogue._interpret',return_value=slots):
  r=catalog_dialogue_reply(db,1,c,'nên mua loại nào tóc tôi đang bị bết')
 assert 'Dầu gội làm sạch hằng ngày' in r.prompt and 'Làm sạch tóc và da đầu' in r.prompt
 assert 'chưa' in r.prompt and 'khẳng định' in r.prompt
 assert 'trị tóc bết' not in r.prompt


@pytest.mark.parametrize('q',[
 'tôi muốn đặt hàng sản phẩm Dầu gội làm sạch hằng ngày 250ml shop còn bao nhiêu hàng',
 'Tôi muốn đặt hàng Dầu gội làm sạch hằng ngày 250ml — 109.000 đồng, còn bao nhiêu hàng?',
 'Cho tôi chốt đơn dầu gội làm sạch hằng ngày 250ml, shop còn bao nhiêu hàng?',
])
def test_purchase_preface_does_not_hide_explicit_stock_question(setup,q):
 from app.models.sales import Order
 from app.models.customer_collection import CustomerCollectionSession
 db,c,p,*_=setup;p.name='Dầu gội làm sạch hằng ngày 250ml';p.stock_quantity=30;p.reserved_quantity=0;p.metadata_={'product_profile':{'category':'Dầu gội'}};db.commit()
 before=(db.query(Order).count(),db.query(CustomerCollectionSession).count())
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('must answer stock without AI')):
  r=catalog_dialogue_reply(db,1,c,q)
 assert '30' in r.prompt and 'có thể bán' in r.prompt
 assert r.metadata['catalog_dialogue']['shortlist']==[p.id]
 assert (db.query(Order).count(),db.query(CustomerCollectionSession).count())==before
