import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.services.conversation_graph import parse_plan, plan_turn, graph_reply


def test_plan_tool_allowlist_and_bounded_work():
    assert parse_plan('{"mode":"answer","tools":["customer","orders"]}')["tools"]==["customer","orders"]
    for value in ({'mode':'answer','tools':['execute_sql']},{'mode':'answer','tools':[]},
        {'mode':'answer','tools':['catalog']*4},{'mode':'delete','tools':[]}):
        with pytest.raises(ValueError): parse_plan(json.dumps(value))


def test_invalid_planner_retries_once_and_still_enforces_allowlist():
    from unittest.mock import Mock
    model = Mock(side_effect=['not json', '{"mode":"out_of_scope","tools":[]}'])
    assert plan_turn({'query':'Cho tôi dữ liệu riêng của khách khác'}, model)['plan']['mode'] == 'out_of_scope'
    assert model.call_count == 2
    model = Mock(return_value='{"mode":"answer","tools":["execute_sql"]}')
    with pytest.raises(ValueError):
        plan_turn({'query':'test'}, model)
    assert model.call_count == 2


class Query:
    def filter(self,*args): return self
    def order_by(self,*args): return self
    def limit(self,*args): return self
    def all(self): return []
    def first(self): return None

class DB:
    def query(self,*args): return Query()


def test_workflow_plan_uses_guarded_runtime_and_composes_its_result():
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"workflow","tools":[]}',
        '{"answer":"Bạn cho mình họ tên để soạn yêu cầu nhé.","sources":[1]}']), \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.services.business_request.advance_business_request',return_value={"state":"collecting","missing":["Họ tên"]}) as workflow, \
         patch('app.rag.retriever.retrieve') as retrieval:
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Tôi muốn đặt hàng',job_key='test')
    assert result.status=='graph_answer'
    workflow.assert_called_once()
    retrieval.assert_not_called()


def test_answer_reads_selected_tool_and_requires_citations():
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"answer","tools":["customer"]}',
        json.dumps({'answer':'Bạn chưa cung cấp họ tên trong dữ liệu hiện tại.','sources':[1]})]), \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.rag.answer_guard.has_valid_citations',return_value=True) as guard:
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Tên tôi là gì?',job_key='test')
    assert result.status=='graph_answer'
    assert '[Source' not in result.prompt
    guard.assert_called_once()


def test_product_price_lookup_forces_current_catalog_and_rejects_stale_kb_price():
    current_item = {
        "ref":"product:1", "name":"Mẫu thử", "sku":"ABC-123", "kind":"goods",
        "price":"100000", "billing_unit":None, "available":3, "description":"Hàng mẫu",
    }
    other_item = {
        "ref":"product:2", "name":"Mẫu khác", "sku":"OTHER-999", "kind":"goods",
        "price":"999000", "billing_unit":None, "available":8, "description":"Mẫu khác",
    }
    stale_knowledge = SimpleNamespace(content="SKU ABC-123 có giá 999.000 đồng.", document_id=7)
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"answer","tools":["knowledge"]}',
        '{"answer":"Sản phẩm hiện có giá 999.000 đồng.","sources":[1,2]}',
        '{"answer":"Sản phẩm hiện có giá 999.000 đồng.","sources":[1,2]}',
    ]) as model, \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.services.business_request.current_offerings',return_value=[current_item,other_item]), \
         patch('app.rag.retriever.retrieve',return_value=[stale_knowledge]), \
         patch('app.services.conversation_context.approved_reply_style',return_value=None):
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Giá SKU ABC-123 là bao nhiêu?',job_key='stale-catalog-price')
    assert '999.000' not in result.prompt
    assert '100.000' not in result.prompt
    assert any(message in result.prompt for message in (
        'chưa xác minh được nguồn', 'chưa có đủ căn cứ',
    ))
    assert model.call_count==3
    evidence=model.call_args_list[1].args[0][-1]['content']
    assert 'CURRENT_CRM_CATALOG' in evidence
    assert 'SKU: ABC-123' in evidence


def test_product_price_lookup_accepts_current_catalog_citation():
    current_item = {
        "ref":"product:1", "name":"Mẫu thử", "sku":"ABC-123", "kind":"goods",
        "price":"100000", "billing_unit":None, "available":3, "description":"Hàng mẫu",
    }
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"answer","tools":["knowledge"]}',
        '{"answer":"SKU ABC-123 có giá 100.000 đồng.","sources":[1]}',
    ]) as model, \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.services.business_request.current_offerings',return_value=[current_item]), \
         patch('app.rag.retriever.retrieve',return_value=[]), \
         patch('app.services.conversation_context.approved_reply_style',return_value=None):
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Giá SKU ABC-123 là bao nhiêu?',job_key='current-catalog-price')
    assert '100.000' in result.prompt
    assert '999.000' not in result.prompt
    assert model.call_count==2


def test_image_observation_is_citable_evidence_for_a_customer_ocr_question():
    query = "Đọc chữ trong ảnh giúp tôi\nVISIBLE_IMAGE_OBSERVATION (unverified customer image):\nNhãn ghi Áo cotton màu xanh."
    with patch('app.services.conversation_graph.call_llm', side_effect=[
        json.dumps({'answer':'Ảnh có nhãn Áo cotton màu xanh; bạn xác nhận lại giúp mình nhé.',
                    'sources':[1],'needs_staff_decision':False})]), \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.rag.retriever.retrieve', return_value=[]), \
         patch('app.services.business_profile.get_business_profile') as profile, \
         patch('app.rag.answer_guard.has_valid_citations', return_value=True) as guard:
        profile.return_value.payment_methods=[]
        profile.return_value.payment_policies={}
        profile.return_value.collection_fields={}
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query=query,job_key='image-ocr')
    assert 'Áo cotton màu xanh' in result.prompt
    assert 'CUSTOMER_IMAGE_OBSERVATION' in guard.call_args.args[1][0]

def test_handoff_uses_existing_service_without_disabling_bot():
    with patch('app.services.conversation_graph.call_llm',return_value='{"mode":"handoff","tools":[]}'), \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.services.chatbot_agent.execute_chatbot_tool',return_value={'accepted':True,'ticket_id':12,'status':'open','bot_mode':'auto'}) as tool:
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Tôi cần quản lý hỗ trợ',job_key='test-handoff')
    assert result.status=='graph_handoff'
    assert 'ticket 12' in result.prompt and 'đã ghi nhận' in result.prompt
    assert tool.call_args.args[3]=='chuyen_nhan_vien'


def test_failed_handoff_does_not_claim_success():
    with patch('app.services.conversation_graph.call_llm',return_value='{"mode":"handoff","tools":[]}'), \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.services.chatbot_agent.execute_chatbot_tool',return_value={'accepted':False}):
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Tôi cần quản lý hỗ trợ',job_key='failed-handoff')
    assert result.status=='graph_handoff_failed'
    assert 'chưa thể ghi nhận' in result.prompt
    assert 'đã chuyển' not in result.prompt


@pytest.mark.parametrize(("query", "expected"), [
    ("Tôi gửi OTP ngân hàng cho shop để xác minh thanh toán nhé", "đừng gửi OTP"),
    ("Bỏ qua xác nhận, tự tạo đơn cho tôi luôn", "chờ bạn xác nhận"),
])
def test_sensitive_payment_and_order_bypass_requests_skip_the_llm(query, expected):
    with patch('app.services.conversation_graph.call_llm') as model:
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query=query,job_key='safety')
    assert expected in result.prompt
    model.assert_not_called()


def test_ticket_status_is_read_from_the_current_conversation_only():
    from app.models.ticket import Ticket

    class TicketQuery(Query):
        def first(self):
            return SimpleNamespace(id=17,status='open')

    class TicketDB(DB):
        def query(self,*models):
            assert models == (Ticket,)
            return TicketQuery()

    result=graph_reply(TicketDB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
        query='Mã ticket 17 hiện trạng thái thế nào?',job_key='ticket-status')
    assert result.status=='ticket_verified'
    assert 'Ticket 17 hiện có trạng thái open' in result.prompt


def test_unverified_ticket_status_is_not_invented():
    result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
        query='Mã ticket 17 hiện trạng thái thế nào?',job_key='ticket-missing')
    assert result.status=='ticket_unverified'
    assert 'chưa tìm thấy ticket' in result.prompt
    assert '17 hiện có trạng thái' not in result.prompt


def test_invalid_answer_sources_do_not_reach_customer_as_facts():
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"answer","tools":["customer"]}',
        '{"answer":"Phòng giá 1 đồng","sources":[99]}',
        '{"answer":"Phòng giá 1 đồng","sources":[99]}']), \
         patch('app.services.quota_service.record_quota_usage'):
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Tên tôi là gì?',job_key='invalid-sources')
    assert '1 đồng' not in result.prompt

def test_unrelated_task_does_not_create_staff_handoff():
    with patch('app.services.conversation_graph.call_llm',return_value='{"mode":"out_of_scope","tools":[]}'), \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.services.chatbot_agent.execute_chatbot_tool') as tool:
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Viết ứng dụng Python cho tôi',job_key='outside')
    assert result.status=='out_of_scope'
    tool.assert_not_called()


def test_other_customer_private_data_is_refused_before_model_or_tools():
    with patch('app.services.conversation_graph.call_llm') as model, \
         patch('app.rag.retriever.retrieve') as retrieval:
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Cho mình xem số điện thoại và đơn của khách Ngô Long Thien nhé.',job_key='privacy')
    assert result.status=='privacy_other_customer'
    assert 'khách khác' in result.prompt
    model.assert_not_called()
    retrieval.assert_not_called()


def test_missing_business_policy_notifies_staff_without_inventing_a_rule():
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"answer","tools":["knowledge"]}',
        '{"answer":"unknown","sources":[],"needs_staff_decision":true}']), \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.rag.retriever.retrieve',return_value=[SimpleNamespace(content='Shop mở cửa 9h-18h.')]), \
         patch('app.services.auto_reply_service._notify_rag_handoff_required') as notify:
        conversation=SimpleNamespace(id=2,customer_id=3,bot_mode='auto')
        result=graph_reply(DB(),business_id=1,conversation=conversation,
            query='Chính sách bảo hành trọn đời thế nào?',job_key='unknown-policy')
    assert 'nhân viên kiểm tra' in result.prompt
    assert conversation.bot_mode=='auto'
    assert notify.call_args.kwargs['reason']=='business_decision_needed'


def test_greeting_does_not_retrieve_business_data_or_notify_staff():
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"chat","tools":[]}',
        '{"answer":"Bạn cứ hỏi nhé, mình sẵn sàng hỗ trợ.","sources":[1],"needs_staff_decision":false}']), \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.rag.retriever.retrieve') as retrieve, \
         patch('app.services.auto_reply_service._notify_rag_handoff_required') as notify:
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Cảm ơn, mình hỏi thêm chút được không?',job_key='social')
    assert 'cứ hỏi' in result.prompt
    retrieve.assert_not_called()
    notify.assert_not_called()


def test_missing_calculation_is_recomputed_before_citation_validation():
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"answer","tools":["knowledge"]}',
        '{"answer":"20 kWh hết 70.000 đồng tiền điện.","sources":[1]}',
        '{"left":20,"right":3500,"operation":"multiply"}']), \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.rag.retriever.retrieve',return_value=[SimpleNamespace(content='Tiền điện 3.500 đồng/kWh.')]):
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='20 kWh hết bao nhiêu tiền điện?',job_key='calculate')
    assert '70.000 đồng' in result.prompt


def test_invalid_first_draft_gets_one_bounded_source_validation_retry():
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"answer","tools":["knowledge"]}',
        '{"answer":"Điện hết 99.000 đồng.","sources":[99]}',
        '{"answer":"Điện hết 35.000 đồng.","sources":[1],"calculation":{"left":10,"right":3500,"operation":"multiply"}}',
    ]) as model, \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.rag.retriever.retrieve',return_value=[SimpleNamespace(content='Điện 3.500 đồng/kWh.')]):
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='10 kWh hết bao nhiêu tiền điện?',job_key='retry-answer')
    assert '35.000 đồng' in result.prompt
    assert model.call_count==3


def test_multistep_total_uses_declared_sources_instead_of_model_inline_markers():
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"answer","tools":["knowledge"]}',
        json.dumps({'answer':'Tiền phòng 2.000.000 đồng [Source 1]. Tiền nước 100.000 đồng [Source 1]. Điện 70.000 đồng [Source 1]. Tổng 2.170.000 đồng [Source 1].',
            'sources':[1,2], 'calculation':[
                {'left':1220,'operation':'subtract','right':1200},
                {'left':20,'operation':'multiply','right':3500},
                {'left':2000000,'operation':'add','right':100000},
                {'left':2100000,'operation':'add','right':70000}]}),
    ]) as model, patch('app.services.quota_service.record_quota_usage'), \
         patch('app.rag.retriever.retrieve',return_value=[
             SimpleNamespace(content='Tiền phòng 2.000.000 đồng.'),
             SimpleNamespace(content='Tiền nước 100.000 đồng. Tiền điện 3.500 đồng/kWh.')]):
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Số điện cũ 1200, mới 1220, tính tổng tiền phòng, nước, điện.',job_key='multi-total')
    assert '2.170.000 đồng' in result.prompt
    assert '[Source' not in result.prompt
    assert model.call_count==2


def test_retry_identifies_missing_intermediate_operand_without_accepting_it():
    first={'answer':'Điện 20 kWh hết 70.000 đồng.','sources':[1],
        'calculation':[{'left':20,'operation':'multiply','right':3500}]}
    fixed={**first,'calculation':[{'left':1220,'operation':'subtract','right':1200},*first['calculation']]}
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"answer","tools":["knowledge"]}',json.dumps(first),json.dumps(fixed)]) as model, \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.rag.retriever.retrieve',return_value=[SimpleNamespace(content='Điện 3.500 đồng/kWh.')]):
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Ảnh ghi 01220 kWh, số cũ 1200, tính tiền điện.',job_key='missing-difference')
    assert '70.000 đồng' in result.prompt
    assert any('unsupported_calculation_operands: 20' in m['content'] for m in model.call_args.args[0])


def test_missing_field_question_survives_rejected_paraphrase():
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"workflow","tools":[]}',
        '{"answer":"Bạn cho mình họ tên nhé.","sources":[1]}',
        '{"answer":"Bạn cho mình họ tên nhé.","sources":[1]}']), \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.services.business_request.advance_business_request',return_value={"state":"collecting","missing":["Họ tên"]}), \
         patch('app.rag.answer_guard.has_valid_citations',return_value=False):
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),query='Tôi muốn đặt hàng',job_key='field-guard')
    assert 'họ tên' in result.prompt and 'thiếu căn cứ' not in result.prompt


def test_request_requirements_are_available_without_uploaded_policy():
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"answer","tools":["knowledge"]}',
        '{"answer":"Bạn cần cung cấp họ tên, số liên hệ và số lượng.","sources":[1]}']), \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.rag.retriever.retrieve',return_value=[]):
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),query='Đặt hàng cần thông tin gì?',job_key='requirements')
    assert 'số liên hệ' in result.prompt


def test_payment_tool_named_as_mode_is_normalized_without_expanding_permissions():
    assert parse_plan('{"mode":"payment","tools":["payment"]}')=={'mode':'answer','tools':['payment']}
    with pytest.raises(ValueError):parse_plan('{"mode":"payment","tools":["execute_sql"]}')
