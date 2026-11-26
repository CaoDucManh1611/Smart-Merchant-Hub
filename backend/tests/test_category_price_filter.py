from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.sales import Product
from app.services.catalog_dialogue import catalog_dialogue_reply

@pytest.mark.parametrize('query',[
 'sửa rửa mặt nào > 100k',
 'sửa rửa mặt nào có giá hơn 100.000',
 'sửa rửa mặt nào có giá hơn 100000',
 'Sữa rửa mặt trên 100k',
])
def test_category_and_price_constraints_are_both_applied_without_ai(setup,query):
 db,c,old,*_=setup
 for sku,name,price,category in [('LOW','Sữa rửa mặt bọt mịn 100ml',89000,'Sữa rửa mặt'),('HIGH','Sữa rửa mặt dạng kem 150ml',125000,'Sữa rửa mặt'),('SER','Serum dưỡng da 30ml',229000,'Serum')]:
  db.add(Product(business_id=1,sku=sku,name=name,price=price,stock_quantity=5,status='active',metadata_={'product_profile':{'category':category}}))
 db.commit()
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('category price lookup requires no AI')):
  result=catalog_dialogue_reply(db,1,c,query)
 assert '125.000' in result.prompt and '89.000' not in result.prompt and 'Serum' not in result.prompt


def test_empty_category_price_does_not_fall_back_to_other_category(setup):
 db,c,p,*_=setup;p.name='Sữa rửa mặt';p.price=89000;p.metadata_={'product_profile':{'category':'Sữa rửa mặt'}};db.commit()
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('no AI')):
  r=catalog_dialogue_reply(db,1,c,'Sữa rửa mặt trên 500k')
 assert 'chưa có' in r.prompt and r.metadata['catalog_dialogue']['shortlist']==[]
