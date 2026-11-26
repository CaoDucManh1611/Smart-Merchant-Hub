from types import SimpleNamespace
from decimal import Decimal
from app.services.product_profile import matching_need_products, profile_detail_lines

def item(id,price,need,stock=3):
    return SimpleNamespace(id=id,name="Product",price=Decimal(price),status="active",stock_quantity=stock,reserved_quantity=0,
      metadata_={"product_profile":{"demo":True,"benefits":["Làm sạch"],"suitable_needs":[need]}})

def test_need_and_budget_exclude_unrelated_expensive_and_unavailable():
    rows=[item(1,"119000","rửa mặt"),item(2,"238000","rửa mặt"),item(3,"100000","dưỡng ẩm"),item(4,"90000","rửa mặt",0)]
    assert [p.id for p in matching_need_products(rows,"nhu cầu rửa mặt và dưới 200000",200000)] == [1]
    assert matching_need_products(rows,"rửa mặt",10000)==[]

def test_details_label_demo_and_show_only_supplied_fields():
    lines=profile_detail_lines(item(1,"119000","rửa mặt"))
    assert any("minh họa" in l for l in lines)
    assert any("Công dụng: Làm sạch" == l for l in lines)
    assert not any("Cách dùng:" in l for l in lines)


def test_no_need_does_not_pick_any_product():
    assert matching_need_products([item(1,"119000","rửa mặt")],"gợi ý cho tôi",200000)==[]

def test_inactive_and_reserved_items_excluded():
    p=item(1,"119000","rửa mặt");p.status="archived"
    q=item(2,"119000","rửa mặt");q.reserved_quantity=q.stock_quantity
    assert matching_need_products([p,q],"rửa mặt",200000)==[]

def test_prices_are_live_and_each_matching_variant_can_be_returned():
    products=[item(1,"119000","rửa mặt"),item(2,"238000","rửa mặt")]
    assert len(matching_need_products(products,"rửa mặt",300000))==2
    products[0].price=Decimal("400000")
    assert [p.id for p in matching_need_products(products,"rửa mặt",300000)]==[2]

def test_profile_has_no_effect_on_products_without_it():
    p=item(1,"119000","rửa mặt");p.metadata_={}
    assert profile_detail_lines(p)==[]
    assert matching_need_products([p],"rửa mặt",200000)==[]


def test_specific_need_does_not_recommend_unrelated_general_need():
    general=item(1,"100000","dưỡng ẩm")
    lips=item(2,"150000","dưỡng ẩm môi")
    assert [p.id for p in matching_need_products([general,lips],"nhu cầu dưỡng ẩm môi",200000)]==[2]


def test_budget_does_not_relax_specific_need_to_unrelated_product():
    general=item(1,"100000","dưỡng ẩm")
    lips=item(2,"250000","dưỡng ẩm môi")
    assert matching_need_products([general,lips],"nhu cầu dưỡng ẩm môi",200000)==[]


def test_explicit_category_keeps_recommendation_in_that_group():
    toner=item(1,"100000","dưỡng ẩm")
    wash=item(2,"119000","rửa mặt")
    toner.metadata_["product_profile"]["category"]="Toner"
    wash.metadata_["product_profile"]["category"]="Sữa rửa mặt"
    assert [p.id for p in matching_need_products([toner,wash],"sữa rửa mặt dưỡng ẩm",200000)]==[2]
