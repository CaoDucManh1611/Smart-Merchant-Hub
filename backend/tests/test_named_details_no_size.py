from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.sales import Product
from app.services.catalog_dialogue import catalog_dialogue_reply

@pytest.mark.parametrize("query",[
 "Cho tôi xem thông tin chi tiết của sữa tắm làm sạch dịu nhẹ với",
 "Sữa tắm làm sạch dịu nhẹ ấy tôi muốn xem thông tin của sản phẩm đấy",
])
def test_distinct_name_without_size_is_grounded_without_ai(setup,query):
 db,c,*_=setup
 for sku,name,price in [('ST-250','Sữa tắm làm sạch dịu nhẹ 250ml',99000),('ST-500','Sữa tắm dưỡng da mềm mại 500ml',169000)]:
  db.add(Product(business_id=1,sku=sku,name=name,price=price,status='active',stock_quantity=8,metadata_={'product_profile':{'category':'Sữa tắm','benefits':['Làm sạch cơ thể']}}))
 db.commit()
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('must not call AI')):
  result=catalog_dialogue_reply(db,1,c,query)
 assert '99.000' in result.prompt and 'Công dụng:' in result.prompt
 assert '500ml' not in result.prompt and 'trục trặc' not in result.prompt

@pytest.mark.parametrize('query',['Chào shop nhá','Chào shop','Xin chào shop nhé'])
def test_greeting_does_not_depend_on_ai(setup,query):
 db,c,*_=setup
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('must not call AI')):
  result=catalog_dialogue_reply(db,1,c,query)
 assert result is not None and 'Chào bạn' in result.prompt


@pytest.mark.parametrize('query',[
 'Tôi muốn xem chi tiết sản phẩm mặt nạ đất sét đi',
 'Tôi muốn xem mặt nạ đất sét ấy',
 'Tôi muốn xem chi tiết mặt nạ đất sét',
])
def test_unique_shortened_name_does_not_expand_to_whole_family(setup,query):
 db,c,*_=setup
 for sku,name,price in [('CLAY','Mặt nạ đất sét làm sạch 30g',79000),('GEL-MASK','Mặt nạ dưỡng ẩm dạng gel 100g',189000)]:
  db.add(Product(business_id=1,sku=sku,name=name,price=price,stock_quantity=8,status='active',metadata_={'product_profile':{'category':'Mặt nạ','benefits':['Làm sạch da']}}))
 db.commit()
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('must not call AI')):
  result=catalog_dialogue_reply(db,1,c,query)
 assert '79.000' in result.prompt and 'Công dụng:' in result.prompt
 assert '100g' not in result.prompt and 'phiên bản' not in result.prompt


def test_shortened_name_keeps_real_size_ambiguity(setup):
 db,c,*_=setup
 for size in [30,100]:
  db.add(Product(business_id=1,sku=f'CLAY-{size}',name=f'Mặt nạ đất sét làm sạch {size}g',price=79000,stock_quantity=8,status='active',metadata_={'product_profile':{'category':'Mặt nạ'}}))
 db.commit()
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('must not call AI')):
  result=catalog_dialogue_reply(db,1,c,'Tôi muốn xem chi tiết mặt nạ đất sét')
 assert '30g' in result.prompt and '100g' in result.prompt and 'phiên bản' in result.prompt
