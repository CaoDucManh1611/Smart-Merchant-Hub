from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.message import Message
from app.models.sales import Order,Product
from app.models.customer_collection import CustomerCollectionSession
from app.services.customer_collection_flow import advance_customer_collection


def start(setup):
 db,c,p,*_=setup;p.name='Dầu gội làm sạch hằng ngày 250ml';p.price=109000;p.stock_quantity=30;p.reserved_quantity=0;db.commit()
 db.add(Message(conversation_id=c.id,channel=c.channel,direction='outbound',sender_type='bot',content=f'{p.name}: còn 30 sản phẩm.',metadata_={'catalog_dialogue':{'intent':'detail','shortlist':[p.id]}}));db.commit()
 r=advance_customer_collection(db,business_id=1,customer_id=c.customer_id,conversation_id=c.id,source_channel=c.channel,text='tôi muốn mua 50 cái thì sao')
 return db,c,p,r


def turn(db,c,text):
 return advance_customer_collection(db,business_id=1,customer_id=c.customer_id,conversation_id=c.id,source_channel=c.channel,text=text)

@pytest.mark.parametrize('answer',['lấy','lấy luôn','30 cái sản phẩm nãy bạn nói ấy','ok lấy 30 cái','đồng ý'])
def test_customer_accepts_stock_counteroffer_without_losing_product(setup,answer):
 db,c,p,r=start(setup)
 assert '30' in r.prompt and '50' in r.prompt
 assert r.session_id>0
 r=turn(db,c,answer)
 assert r.current_field=='order_confirmation'
 assert 'Dầu gội' in r.prompt and '3.270.000' in r.prompt
 session=db.get(CustomerCollectionSession,r.session_id)
 assert session.collected_fields['items'][0]['quantity']==30
 assert session.collected_fields['items'][0]['product_id']==p.id
 assert db.query(Order).count()==0 and p.stock_quantity==30 and p.reserved_quantity==0


def test_accepting_offer_rechecks_current_availability(setup):
 db,c,p,r=start(setup);p.stock_quantity=25;db.commit()
 r=turn(db,c,'lấy luôn')
 assert '25' in r.prompt and '30' in r.prompt
 assert r.current_field=='stock_resolution'
 assert db.query(Order).count()==0
 r=turn(db,c,'lấy')
 assert '2.725.000' in r.prompt and r.current_field=='order_confirmation'


def test_rejecting_counteroffer_cancels_without_creating_order(setup):
 db,c,p,r=start(setup)
 r=turn(db,c,'không lấy nữa')
 assert db.get(CustomerCollectionSession,r.session_id).status=='abandoned'
 assert db.query(Order).count()==0


def test_price_only_shortage_does_not_start_checkout(setup):
 db,c,p,*_=setup;p.name='Dầu gội';p.stock_quantity=30;db.commit()
 r=turn(db,c,'Mua 50 Dầu gội hết bao nhiêu?')
 assert db.query(CustomerCollectionSession).count()==0


def test_graph_accepts_counteroffer_without_ai(setup):
 from app.core.config import settings
 from app.services.conversation_graph import graph_reply
 db,c,p,r=start(setup)
 with patch.object(settings,'CATALOG_DIALOGUE_ENABLED',True),patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('active offer must not need AI')):
  r=graph_reply(db,business_id=1,conversation=c,query='lấy luôn',job_key='stock-offer-accept')
 assert 'Dầu gội' in r.prompt and '3.270.000' in r.prompt
 assert db.query(Order).count()==0


def test_accept_offer_then_confirm_reaches_contact_form(setup):
 db,c,p,r=start(setup)
 turn(db,c,'lấy')
 r=turn(db,c,'xác nhận')
 assert 'Tên người nhận:' in r.prompt and 'Số điện thoại:' in r.prompt
 assert db.query(Order).count()==0


def test_offer_sold_out_does_not_suggest_zero(setup):
 db,c,p,r=start(setup);p.stock_quantity=0;db.commit()
 r=turn(db,c,'lấy')
 assert 'hết hàng' in r.prompt and 'lấy 0' not in r.prompt
 assert db.query(Order).count()==0


@pytest.mark.parametrize('approval',['Xác nhận đặt hàng','Xác nhận','Đồng ý đặt hàng'])
def test_accept_stock_offer_then_approve_preserves_quantity(setup,approval):
 db,c,p,r=start(setup)
 r=turn(db,c,'Ok')
 assert '3.270.000' in r.prompt
 r=turn(db,c,approval)
 session=db.get(CustomerCollectionSession,r.session_id)
 assert session.purpose=='order'
 assert session.collected_fields['items'][0]['quantity']==30
 assert session.collected_fields['items'][0]['product_id']==p.id
 from decimal import Decimal
 assert Decimal(session.collected_fields['total_amount'])==3270000
 assert 'Tên người nhận:' in r.prompt
 assert db.query(Order).count()==0
