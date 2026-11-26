from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.sales import Product
from app.services.catalog_dialogue import catalog_dialogue_reply

def slots(intent,group=None,budget=None,product=None,need=None,reference=False):
 return dict(intent=intent,domain="products",group=group,budget=budget,product=product,need=need,reference=reference,confidence=.99)

def products(db):
 rows=[]
 for sku,name,group,price in [("LIP","Son dưỡng môi – Tiêu chuẩn","Son dưỡng môi",280000),("TON","Toner cấp ẩm – Bộ đôi","Toner",284000),("SER","Serum niacinamide – Tiêu chuẩn","Serum",165000),("SHA","Dầu gội dịu nhẹ – Tiêu chuẩn","Dầu gội",303000)]:
  p=Product(business_id=1,sku=sku,name=name,price=price,stock_quantity=5,status="active",metadata_={"product_profile":{"category":group,"benefits":["Demo"],"suitable_needs":[group],"usage":[],"demo":True}})
  db.add(p);rows.append(p)
 db.commit();return rows

@pytest.mark.parametrize("meaning,required,excluded",[
 (slots("budget","Son dưỡng môi",100000),"chưa có","Toner"),
 (slots("budget","Son dưỡng môi"),"ngân sách","Toner"),
 (slots("purchase","áo",product="áo"),"chưa có","Toner"),
 (slots("group",product="áo"),"chưa có","Toner"),
 (slots("other",product="áo"),"chưa tìm thấy","Toner"),
 (slots("usage","Serum",product="Serum niacinamide"),"chưa có hướng dẫn","Toner"),
 (slots("group","Dầu gội"),"Dầu gội","Toner"),
 (slots("inventory","Dầu gội"),"Dầu gội","Toner"),
 (slots("recommend",need="da dầu mụn"),"chưa có thông tin","phù hợp: Toner"),
 (slots("complaint"),"xin lỗi","Toner"),
 (slots("social"),"đang nghe","Toner"),
 (slots("bestseller"),"chưa có thống kê","lên đơn"),
])
def test_backend_enforces_meaning_not_surface_phrase(setup,meaning,required,excluded):
 db,c,*_=setup;products(db)
 with patch("app.services.catalog_dialogue._interpret",return_value=meaning):
  result=catalog_dialogue_reply(db,1,c,"free wording",None)
 assert required in result.prompt and excluded not in result.prompt

def test_known_purchase_keeps_existing_checkout(setup):
 db,c,*_=setup;products(db)
 with patch("app.services.catalog_dialogue._interpret",return_value=slots("purchase","Son dưỡng môi",product="Son dưỡng môi – Tiêu chuẩn")):
  assert catalog_dialogue_reply(db,1,c,"mua Son dưỡng môi – Tiêu chuẩn",None) is None

def test_uncertain_or_unavailable_understanding_never_recommends_arbitrary_item(setup):
 db,c,*_=setup;products(db)
 with patch("app.services.catalog_dialogue._interpret",side_effect=RuntimeError("provider failed")):
  result=catalog_dialogue_reply(db,1,c,"unknown wording",None)
 assert result.status=="dialogue_understanding_unavailable" and "Toner" not in result.prompt


def test_active_checkout_is_not_reinterpreted(setup):
 from app.models.customer_collection import CustomerCollectionSession
 db,c,*_=setup;products(db)
 db.add(CustomerCollectionSession(business_id=1,customer_id=c.customer_id,conversation_id=c.id,purpose="order",status="pending",required_fields=["name"],collected_fields={},current_field="name"));db.commit()
 with patch("app.services.catalog_dialogue._interpret",side_effect=AssertionError("must keep existing collection flow")):
  assert catalog_dialogue_reply(db,1,c,"Tên người nhận: Test",None) is None

def test_unrelated_service_keeps_existing_flow(setup):
 db,c,*_=setup;products(db)
 meaning=slots("other");meaning["domain"]="services"
 with patch("app.services.catalog_dialogue._interpret",return_value=meaning):
  assert catalog_dialogue_reply(db,1,c,"đặt lịch dịch vụ",None) is None

@pytest.mark.parametrize("query",["Dầu gội đi","Gội đầu thì có gì?"])
def test_named_category_ignores_previous_unrelated_list(setup,query):
 from app.models.message import Message
 db,c,*_=setup;rows=products(db)
 db.add(Message(conversation_id=c.id,channel=c.channel,direction="outbound",sender_type="bot",content="Toner cấp ẩm – Bộ đôi",metadata_={"catalog_dialogue":{"group":"Toner","shortlist":[rows[1].id]}}));db.commit()
 with patch("app.services.catalog_dialogue._interpret",return_value=slots("group","Dầu gội",reference=True)):
  result=catalog_dialogue_reply(db,1,c,query,None)
 assert "Dầu gội" in result.prompt and "Toner" not in result.prompt


def test_explicit_unknown_item_does_not_borrow_old_category(setup):
 from app.models.message import Message
 db,c,*_=setup;products(db)
 db.add(Message(conversation_id=c.id,channel=c.channel,direction="outbound",sender_type="bot",content="Toner cấp ẩm",metadata_={"catalog_dialogue":{"group":"Toner"}}));db.commit()
 with patch("app.services.catalog_dialogue._interpret",return_value=slots("group",product="áo",reference=True)):
  result=catalog_dialogue_reply(db,1,c,"cái áo cơ mà",None)
 assert "chưa có áo" in result.prompt and "Toner" not in result.prompt

def test_policy_question_keeps_knowledge_flow(setup):
 db,c,*_=setup;products(db)
 meaning=slots("other");meaning["domain"]="knowledge"
 with patch("app.services.catalog_dialogue._interpret",return_value=meaning):
  assert catalog_dialogue_reply(db,1,c,"chính sách giao hàng",None) is None


def test_handoff_pauses_bot_only_after_accepted_ticket(setup):
 db,c,*_=setup;products(db)
 with patch("app.services.catalog_dialogue._interpret",return_value=slots("handoff")),patch("app.services.chatbot_agent.execute_chatbot_tool",return_value={"accepted":True,"ticket_id":100,"status":"open"}):
  result=catalog_dialogue_reply(db,1,c,"gặp người thật",None)
 assert result.status=="dialogue_handoff" and c.bot_mode=="human"

def test_unaccepted_handoff_does_not_pause_bot(setup):
 db,c,*_=setup;products(db)
 with patch("app.services.catalog_dialogue._interpret",return_value=slots("handoff")),patch("app.services.chatbot_agent.execute_chatbot_tool",return_value={"accepted":False}):
  result=catalog_dialogue_reply(db,1,c,"gặp người thật",None)
 assert result.status=="dialogue_handoff_failed" and c.bot_mode!="human"


def test_contradictory_semantic_labels_are_reviewed_once():
 import json
 from app.services.catalog_dialogue import _interpret
 _interpret.cache_clear()
 first=slots("social","Serum",product="serum")
 second=slots("usage","Serum",product="serum")
 payload=json.dumps({"categories":["Serum"],"prior":[],"state":{},"current":"Bày mình xài serum"})
 with patch("app.services.catalog_dialogue.call_structured",side_effect=[first,second]) as remote:
  assert _interpret(payload,"test")['intent']=="usage"
  assert remote.call_count==2
 _interpret.cache_clear()



def test_complaint_retains_recent_budget_without_requiring_reference_word(setup):
 from app.models.message import Message
 db,c,*_=setup;products(db)
 db.add(Message(conversation_id=c.id,channel=c.channel,direction="outbound",sender_type="bot",content="Chưa có son trong mức giá này",metadata_={"catalog_dialogue":{"group":"Son dưỡng môi","budget":100000,"intent":"budget","shortlist":[]}}));db.commit()
 with patch("app.services.catalog_dialogue._interpret",return_value=slots("complaint",reference=False)):
  result=catalog_dialogue_reply(db,1,c,"tư vấn lệch quá",None)
 assert "100.000" in result.prompt and "son dưỡng môi" in result.prompt and "Toner" not in result.prompt

def test_generic_followup_inherits_bestseller_state(setup):
 from app.models.message import Message
 db,c,*_=setup;products(db)
 db.add(Message(conversation_id=c.id,channel=c.channel,direction="outbound",sender_type="bot",content="Shop chưa có thống kê",metadata_={"catalog_dialogue":{"intent":"bestseller","group":None,"shortlist":[]}}));db.commit()
 with patch("app.services.catalog_dialogue._interpret",return_value=slots("recommend")):
  result=catalog_dialogue_reply(db,1,c,"gợi ý tiếp đi",None)
 assert "chưa có thống kê" in result.prompt and "lên đơn" not in result.prompt

def test_family_alias_does_not_silently_choose_single_variant(setup):
 db,c,*_=setup;products(db)
 db.add(Product(business_id=1,sku="LIP-DUO",name="Son dưỡng môi – Bộ đôi",price=560000,stock_quantity=5,status="active",metadata_={"product_profile":{"category":"Son dưỡng môi"}}));db.commit()
 with patch("app.services.catalog_dialogue._interpret",return_value=slots("recommend","Son dưỡng môi",product="Son dưỡng môi")):
  result=catalog_dialogue_reply(db,1,c,"tư vấn son dưỡng",None)
 assert "Son dưỡng môi – Tiêu chuẩn" in result.prompt and "Son dưỡng môi – Bộ đôi" in result.prompt
