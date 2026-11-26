from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.sales import Product
from app.services.catalog_dialogue import catalog_dialogue_reply
from app.services.price_constraints import price_constraints,matches_price

@pytest.mark.parametrize('condition,expected',[
 ('> 200k',[201000]),('>= 200k',[200000,201000]),
 ('< 200k',[199000]),('<= 200k',[199000,200000]),
 ('≥ 200 nghìn',[200000,201000]),('≤ 200.000',[199000,200000]),
 ('không dưới 200k',[200000,201000]),('không trên 200k',[199000,200000]),
 ('trên 200k',[201000]),('lớn hơn 200k',[201000]),
 ('nhỏ hơn hoặc bằng 200k',[199000,200000]),
])
def test_price_comparison_boundaries_and_no_ai(setup,condition,expected):
 db,c,p,*_=setup;p.status='inactive'
 rows=[]
 for amount in [199000,200000,201000]:
  row=Product(business_id=1,sku=f'PRICE-{amount}',name=f'Giá thử {amount}',price=amount,stock_quantity=3,status='active');db.add(row);rows.append(row)
 db.commit()
 q='Tôi muốn mua sản phẩm nào '+condition
 constraints=price_constraints(q)
 assert constraints
 assert [int(row.price) for row in rows if matches_price(row.price,constraints)]==expected
 with patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('comparison needs no AI')):
  r=catalog_dialogue_reply(db,1,c,q)
 assert r and r.status=='catalog_dialogue'
 assert sorted(r.metadata['catalog_dialogue']['shortlist'])==sorted(row.id for row in rows if int(row.price) in expected)


def test_range_intersection():
 cs=price_constraints('giá >200k và <=300k')
 assert len(cs)==2
 assert not matches_price(200000,cs) and matches_price(250000,cs) and matches_price(300000,cs) and not matches_price(301000,cs)
