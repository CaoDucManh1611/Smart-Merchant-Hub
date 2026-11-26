from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.sales import Product
from app.services.catalog_dialogue import catalog_dialogue_reply

@pytest.mark.parametrize('q',[
 'Bạn cho tôi xem tất cả các sản phẩm của bạn với',
 'Cho mình xem toàn bộ sản phẩm của cửa hàng nhé',
 'Bạn có thể gợi ý sản phẩm được không',
 'Shop tư vấn giúp mình chọn sản phẩm với',
 'Tôi muốn tìm sản phẩm nào dưới 200k',
 'Có sản phẩm nào dưới 200 nghìn không?',
])
def test_basic_request_survives_ai_outage(setup,q):
 db,c,*_=setup
 db.add(Product(business_id=1,sku='BASIC-199',name='Sản phẩm giá thấp',price=199000,stock_quantity=3,status='active'))
 db.add(Product(business_id=1,sku='BASIC-200',name='Sản phẩm đúng ngưỡng',price=200000,stock_quantity=3,status='active'))
 db.commit()
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('basic request must not need AI')):
  result=catalog_dialogue_reply(db,1,c,q)
 assert result is not None and result.status!='dialogue_understanding_unavailable'
 if 'gợi ý' in q or 'tư vấn' in q:
  assert 'nhu cầu' in result.prompt or 'đáp ứng' in result.prompt
 elif 'dưới' in q:
  assert 'Sản phẩm giá thấp' in result.prompt
  assert 'Sản phẩm đúng ngưỡng' not in result.prompt
 else:assert 'Sản phẩm đúng ngưỡng' in result.prompt
