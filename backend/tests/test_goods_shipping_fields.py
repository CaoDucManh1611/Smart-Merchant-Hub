from test_business_request import setup
from app.schemas.business_profile import BusinessProfile
from app.services.business_request import advance_business_request
from app.models.sales import Order


def test_goods_asks_shipping_before_review_and_order(setup):
 db,c,p,*_=setup
 text='Tôi mua 1 Hàng thử, Khách Kiểm Tra, 0900000011, chuyển khoản'
 action={'action':'collect','action_evidence':text,'offering_ref':f'product:{p.id}','fields':{
  'name':{'value':'Khách Kiểm Tra','evidence':'Khách Kiểm Tra'},
  'phone':{'value':'0900000011','evidence':'0900000011'},
  'quantity':{'value':'1','evidence':'1'},
  'payment_method':{'value':'bank_transfer','evidence':'chuyển khoản'}}}
 r=advance_business_request(db,business_id=1,conversation=c,query=text,history=[],job_key='shipping-required',_interpreted_action=action)
 assert r['state']=='collecting'
 assert 'Địa chỉ nhận hàng' in r['missing'] and 'Email' in r['missing']
 assert db.query(Order).count()==0


def test_services_do_not_require_shipping():
 p=BusinessProfile()
 assert 'address' in [f.key for f in p.collection_fields['goods']]
 assert 'address' not in [f.key for f in p.collection_fields['service']]
