from copy import deepcopy
from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.customer_collection import CustomerCollectionSession
from app.models.sales import Order
from app.services.quantity_price_quote import pending_quantity_quote


def pending(data):
    db, conversation, product, *_ = data
    product.name="Toner cấp ẩm – Tiêu chuẩn"; product.price=142000
    session=CustomerCollectionSession(business_id=1,customer_id=conversation.customer_id,
        conversation_id=conversation.id,source_channel=conversation.channel,purpose="business_request",
        status="partial",current_field="name",required_fields=["name","phone","quantity"],
        collected_fields={"offering_ref":f"product:{product.id}","values":{"quantity":2},"phase":"collecting"})
    db.add(session);db.commit()
    return session


@pytest.mark.parametrize("query", ["mua 2 sản phẩm thì giá bao nhiêu",
    "nếu tôi mua 2 sản phẩm thì hoá đơn cần trả là bao nhiêu", "tổng tiền cần trả bao nhiêu"])
def test_quantity_question_uses_live_price_without_llm_or_changing_request(setup,query):
    from app.services.conversation_graph import graph_reply
    db,conversation,product,*_=setup
    session=pending(setup);before=deepcopy(session.collected_fields)
    with patch("app.services.conversation_graph.call_llm",side_effect=AssertionError("no model arithmetic")):
        reply=graph_reply(db,business_id=1,conversation=conversation,query=query,job_key="quantity-test")
    assert "142.000" in reply.prompt and "284.000" in reply.prompt
    assert "2 × 142.000" in reply.prompt
    assert session.collected_fields==before and session.current_field=="name"
    assert db.query(Order).count()==0
    product.price=150000;db.flush()
    assert "300.000" in pending_quantity_quote(db,1,query,session)


@pytest.mark.parametrize("query", ["giá bao nhiêu", "mua 2 toner và 3 mặt nạ giá bao nhiêu",
    "mua 2 sản phẩm giảm giá bao nhiêu", "mua 2 sữa rửa mặt giá bao nhiêu",
    "mua 0 sản phẩm giá bao nhiêu", "mua 10001 sản phẩm giá bao nhiêu"])
def test_ambiguous_or_policy_questions_do_not_get_invented_total(setup,query):
    session=pending(setup)
    assert pending_quantity_quote(setup[0],1,query,session) is None


def test_quote_respects_fixed_charges_stock_and_tenant_scope(setup):
    from app.services.business_profile import get_business_profile,save_business_profile
    from app.schemas.business_profile import PaymentPolicy
    db=setup[0];session=pending(setup)
    profile=get_business_profile(db,1)
    profile.payment_policies['goods']=PaymentPolicy(mode='order_total',label='Tiền hàng',
        fixed_charges=[{'label':'Phí cố định','amount':10000}])
    save_business_profile(db,1,profile)
    setup[2].stock_quantity=1;db.flush()
    quote=pending_quantity_quote(db,1,"mua 2 sản phẩm thì giá bao nhiêu",session)
    assert "294.000" in quote and "Phí cố định: 10.000" in quote
    assert "chưa đủ" in quote
    assert pending_quantity_quote(db,2,"mua 2 sản phẩm thì giá bao nhiêu",session) is None
