from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.sales import Product
from app.services.catalog_dialogue import catalog_dialogue_reply

@pytest.mark.parametrize('q',[
 'Shop của bạn có bao nhiêu sản phẩm mặt nạ đất sét vâyh',
 'Shop của bạn có bao nhiêu mặt nạ đất sét vậy',
 'Giá của mặt nạ đất sét là bao nhiêu vậy',
])
def test_short_name_stock_and_price_are_grounded_without_ai(setup,q):
 db,c,*_=setup
 for sku,name,price,stock in [('CLAY','Mặt nạ đất sét làm sạch 30g',79000,18),('MASK-GEL','Mặt nạ dưỡng ẩm dạng gel 100g',189000,24)]:
  db.add(Product(business_id=1,sku=sku,name=name,price=price,stock_quantity=stock,reserved_quantity=0,status='active',metadata_={'product_profile':{'category':'Mặt nạ'}}))
 db.commit()
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('must not call AI')):
  r=catalog_dialogue_reply(db,1,c,q)
 assert 'Mặt nạ đất sét làm sạch 30g' in r.prompt
 assert '100g' not in r.prompt and 'trục trặc' not in r.prompt
 if 'Giá' in q:assert '79.000' in r.prompt
 else:assert '18' in r.prompt and '1 mẫu' in r.prompt


def test_stock_reports_available_not_reserved_units(setup):
 db,c,p,*_=setup;p.name='Mặt nạ đất sét làm sạch 30g';p.stock_quantity=18;p.reserved_quantity=3;p.metadata_={'product_profile':{'category':'Mặt nạ'}};db.commit()
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('must not call AI')):
  r=catalog_dialogue_reply(db,1,c,'Shop có bao nhiêu mặt nạ đất sét vậy')
 assert '15' in r.prompt and '18' not in r.prompt
