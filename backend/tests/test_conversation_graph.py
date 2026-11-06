import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.services.conversation_graph import (
    _missing_evidence_reply,
    graph_reply,
    parse_plan,
    plan_turn,
)
from app.services.capability_registry import CAPABILITY_IDS


@pytest.fixture(autouse=True)
def graph_workspace_has_explicit_test_grants(monkeypatch):
    # Existing graph behavior tests model a configured shop. Separate tests
    # override this fixture to prove the default/disabled authorization path.
    monkeypatch.setattr(
        "app.tenancy.workspace_modules.get_workspace_config",
        lambda _db, _business_id: {
            "business_model": "MULTI_SERVICE",
            "industry_ids": [],
            "enabled_modules": ["appointments"],
            "enabled_capabilities": list(CAPABILITY_IDS),
            "configuration_rejected": False,
            "config_version": 1,
        },
    )


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


def test_enabled_sales_journey_runs_once_without_extra_llm_and_fails_closed_without_policy(
    monkeypatch, tmp_path
):
    from app.core.config import settings
    from app.services.sales_journey_engine import SalesJourneyEngine

    monkeypatch.setattr(settings, "SALES_JOURNEY_ENGINE_ENABLED", True)
    monkeypatch.setattr(settings, "SALES_JOURNEY_PERSISTENCE_PURPOSE", "")
    monkeypatch.setattr(settings, "SALES_JOURNEY_PERSISTENCE_POLICY_VERSION", "")
    monkeypatch.setattr("app.rag.run_logger._log_path", lambda: tmp_path / "rag.jsonl")

    evaluate = SalesJourneyEngine.evaluate
    evaluations = []

    def count_evaluation(self, *args, **kwargs):
        evaluations.append((args, kwargs))
        return evaluate(self, *args, **kwargs)

    monkeypatch.setattr(SalesJourneyEngine, "evaluate", count_evaluation)
    with patch(
        "app.services.conversation_graph.call_llm",
        side_effect=[
            '{"mode":"chat","tools":[]}',
            '{"answer":"Shop có thể hỗ trợ bạn.","sources":[]}',
        ],
    ) as model, patch("app.services.quota_service.record_quota_usage"), patch(
        "app.rag.serving.retrieve_shop_knowledge", return_value=[]
    ), patch("app.services.business_request.current_offerings", return_value=[]), patch(
        "app.services.auto_reply_service._notify_rag_handoff_required"
    ):
        result = graph_reply(
            DB(), business_id=17, conversation=SimpleNamespace(id=21, customer_id=31),
            query="Shop có thể hỗ trợ mình không?", job_key="journey-flag-on:42",
        )

    assert result.status == "graph_answer"
    assert len(evaluations) == 1
    assert model.call_count == 2
    assert "sales_journey_state" not in (result.metadata or {})


class Query:
    def filter(self,*args): return self
    def order_by(self,*args): return self
    def limit(self,*args): return self
    def all(self): return []
    def first(self): return None

class DB:
    def query(self,*args): return Query()
    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    def execute(self,*args,**kwargs): return Query()


def test_disabled_catalog_shortcut_is_denied_and_audited_before_llm(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.tenancy.workspace_modules.get_workspace_config",
        lambda _db, _business_id: {
            "business_model": "RETAIL", "industry_ids": [],
            "enabled_capabilities": ["CORE_CRM"], "configuration_rejected": False,
            "config_version": 1,
        },
    )
    monkeypatch.setattr("app.rag.run_logger._log_path", lambda: tmp_path / "rag.jsonl")
    with patch("app.services.auto_reply_service._is_product_attribute_question", return_value=True), \
         patch("app.services.auto_reply_service._deterministic_customer_reply") as direct_lookup, \
         patch("app.services.conversation_graph.call_llm") as model:
        result = graph_reply(
            DB(), business_id=17, conversation=SimpleNamespace(id=21, customer_id=31),
            query="Giá sản phẩm này bao nhiêu?", job_key="capability-denied:42",
        )

    assert result.status == "workspace_capability_disabled"
    assert result.metadata["capability_authorization"]["missing_capabilities"] == ["RETAIL_TOOLS"]
    direct_lookup.assert_not_called()
    model.assert_not_called()
    log_record = json.loads((tmp_path / "rag.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert log_record["status"] == "capability_denied"
    assert log_record["capability_authorization"]["allowed"] is False


def test_disabled_catalog_selection_is_denied_before_product_identity_lookup(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.tenancy.workspace_modules.get_workspace_config",
        lambda _db, _business_id: {
            "business_model": "RETAIL", "industry_ids": [],
            "enabled_capabilities": ["CORE_CRM"], "configuration_rejected": False,
            "config_version": 1,
        },
    )
    monkeypatch.setattr("app.rag.run_logger._log_path", lambda: tmp_path / "rag.jsonl")
    with patch("app.services.auto_reply_service._catalog_request_has_identity_overlap") as identity_lookup, \
         patch("app.services.auto_reply_service._deterministic_customer_reply") as direct_lookup, \
         patch("app.services.conversation_graph.call_llm") as model:
        result = graph_reply(
            DB(), business_id=17, conversation=SimpleNamespace(id=21, customer_id=31),
            query="Mình cần mua lọc gió cho xe tay ga", job_key="selection-capability-denied",
        )

    assert result.status == "workspace_capability_disabled"
    identity_lookup.assert_not_called()
    direct_lookup.assert_not_called()
    model.assert_not_called()


def test_appointment_only_plan_skips_product_identity_queries(monkeypatch):
    monkeypatch.setattr(
        "app.tenancy.workspace_modules.get_workspace_config",
        lambda _db, _business_id: {
            "business_model": "APPOINTMENT_SERVICE", "industry_ids": [],
            "enabled_capabilities": ["CORE_CRM", "APPOINTMENT_TOOLS"],
            "configuration_rejected": False, "config_version": 1,
        },
    )
    with patch("app.services.auto_reply_service._is_catalog_selection_request") as selection_probe, \
         patch("app.services.auto_reply_service._catalog_request_has_identity_overlap") as identity_probe, \
         patch("app.services.business_request.current_offerings", return_value=[]), \
         patch("app.services.auto_reply_service._notify_rag_handoff_required"), \
         patch("app.services.quota_service.record_quota_usage"):
        result = graph_reply(
            DB(), business_id=17, conversation=SimpleNamespace(id=21, customer_id=31),
            query="Shop có dịch vụ bảo dưỡng xe máy không?", job_key="service-catalog-no-product-probe",
        )

    assert result.status == "graph_answer"
    selection_probe.assert_not_called()
    identity_probe.assert_not_called()


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
         patch('app.services.conversation_context.approved_reply_style',return_value=None), \
         patch('app.services.auto_reply_service._notify_rag_handoff_required'):
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query='Giá SKU ABC-123 là bao nhiêu?',job_key='stale-catalog-price')
    assert '999.000' not in result.prompt
    assert '100.000' not in result.prompt
    assert any(message in result.prompt for message in (
        'chưa xác minh được nguồn', 'chưa có đủ căn cứ', 'chưa thể xác minh đầy đủ',
    ))
    # Exact product facts now take the authorized deterministic catalog route;
    # the graph should not make the old extra draft/repair calls for this turn.
    assert model.call_count==2
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


def test_product_fact_reply_is_composed_inside_graph_after_catalog_authorization(monkeypatch, tmp_path):
    monkeypatch.setattr("app.rag.run_logger._log_path", lambda: tmp_path / "rag.jsonl")
    direct_reply = ("Mẫu thử hiện có giá 100.000 đồng và còn 3 sản phẩm.", "product_fact")
    with patch("app.services.auto_reply_service._is_product_attribute_question", return_value=True), \
         patch("app.services.auto_reply_service._deterministic_customer_reply", return_value=direct_reply) as lookup, \
         patch("app.services.conversation_graph.call_llm", side_effect=AssertionError("catalog fact is deterministic")):
        result = graph_reply(
            DB(), business_id=17, conversation=SimpleNamespace(id=21, customer_id=31),
            query="Giá sản phẩm này bao nhiêu?", job_key="catalog-fact-through-graph",
        )

    assert result.status == "graph_answer"
    assert result.prompt == direct_reply[0]
    lookup.assert_called_once()
    records = [json.loads(line) for line in (tmp_path / "rag.jsonl").read_text(encoding="utf-8").splitlines()]
    graph_record = next(record for record in records if record["operation"] == "conversation_graph")
    assert graph_record["tool_status"] == "completed"
    assert graph_record.get("catalog_reply_mode") == "product_fact"
    assert "live_catalog_shortcut" not in str(graph_record)


def test_product_image_followup_uses_recent_tenant_catalog_entity_without_llm():
    product = SimpleNamespace(id=9, business_id=17, name="Dầu gội dịu nhẹ", status="active")
    with patch("app.services.product_resolver.resolve_prior_product_mention", return_value=product) as prior, \
         patch("app.services.product_image_match.product_image_url", return_value="https://cdn.example/shampoo.png"), \
         patch("app.services.conversation_graph.call_llm", side_effect=AssertionError("image presence is a catalog fact")):
        result = graph_reply(
            DB(), business_id=17, conversation=SimpleNamespace(id=21, customer_id=31),
            query="Bạn có hình ảnh không?", job_key="product-image-followup",
        )

    assert result.status == "graph_answer"
    assert "Dầu gội dịu nhẹ" in result.prompt
    assert "https://cdn.example/shampoo.png" in result.prompt
    prior.assert_called_once()
    assert prior.call_args.kwargs["business_id"] == 17
    assert prior.call_args.kwargs["conversation_id"] == 21


def test_explicit_catalog_comparison_bypasses_generic_need_discovery_question(monkeypatch):
    from app.services.universal_sales_brain import NeedsDiscovery

    query = "So sánh Áo Alpha và Áo Beta về giá và tồn kho."
    discovery = NeedsDiscovery(
        intent="product_question", confidence=0.9,
        next_best_question="Bạn đang tìm sản phẩm nào?",
    )
    monkeypatch.setattr(
        "app.services.universal_sales_brain.discover_needs",
        lambda *_args, **_kwargs: discovery,
    )
    monkeypatch.setattr("app.services.conversation_memory.load_reply_memory", lambda *_a, **_k: {})
    expected = ("Áo Alpha còn 3, Áo Beta còn 5; mình đã so sánh theo danh mục.", "product_comparison")
    with patch(
        "app.services.auto_reply_service._deterministic_customer_reply", return_value=expected
    ) as deterministic, patch(
        "app.services.conversation_graph.call_llm", side_effect=AssertionError("comparison should use catalog shortcut")
    ), patch("app.rag.run_logger.RagRunLog"):
        result = graph_reply(
            DB(), business_id=17, conversation=SimpleNamespace(id=21, customer_id=31),
            query=query, job_key="comparison-discovery-gate",
        )

    assert result.status == "graph_answer"
    assert result.prompt == expected[0]
    deterministic.assert_called_once()


def test_read_only_mirror_purchase_question_uses_catalog_facts_without_transaction_workflow():
    deterministic_reply=(
        "Mình kiểm tra được trong danh mục:\n"
        "- Gương M10 trái: 115.000 đồng, còn 21\n"
        "- Gương M10 phải: 115.000 đồng, còn 18\n"
        "Tổng theo giá niêm yết: 230.000 đồng",
        "product_multi_fact_catalog",
    )
    with patch("app.services.auto_reply_service._deterministic_customer_reply", return_value=deterministic_reply) as direct, \
         patch("app.services.auto_reply_service._is_product_fact_question", return_value=True), \
         patch("app.services.auto_reply_service._is_product_attribute_question", return_value=False), \
         patch("app.services.auto_reply_service._is_catalog_selection_request", return_value=False), \
         patch("app.services.auto_reply_service._is_specific_product_lookup", return_value=False), \
         patch("app.rag.run_logger.RagRunLog"), \
         patch("app.services.quota_service.record_quota_usage"):
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query="Tôi muốn mua gương M10 trái và phải. Tổng tiền là bao nhiêu, mỗi bên còn hàng không?",
            job_key="mirror-read-only")

    assert "230.000 đồng" in result.prompt
    direct.assert_called_once()


def test_partial_product_code_is_routed_to_catalog_before_rag():
    with patch("app.services.auto_reply_service._partial_catalog_code_prefix",return_value="xm-ma-phanh-"), \
         patch("app.services.auto_reply_service._deterministic_customer_reply",return_value=(
             "Mã bạn gửi chưa đầy đủ. Sản phẩm khớp là Má phanh đĩa trước Vision 110, còn 5 sản phẩm.",
             "product_partial_code_match",
         )) as direct, \
         patch("app.rag.run_logger.RagRunLog"), \
         patch("app.services.quota_service.record_quota_usage"), \
         patch("app.services.conversation_graph.call_llm") as model:
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query="Mã XM-MA-PHANH- còn bán không?",job_key="partial-code")

    assert "chưa đầy đủ" in result.prompt
    direct.assert_called_once()
    model.assert_not_called()


def test_service_price_reply_does_not_append_unsolicited_calendar_question():
    service={
        "ref":"service:4", "name":"Công thay bộ nhông sên dĩa", "kind":"service",
        "price":"180000", "billing_unit":"lần", "duration_minutes":120,
        "available":None, "description":"Thay bộ nhông sên dĩa",
    }
    with patch("app.services.business_request.current_offerings",return_value=[service]), \
         patch("app.services.quota_service.record_quota_usage"), \
         patch("app.services.conversation_graph.call_llm") as model:
        result=graph_reply(DB(),business_id=1,conversation=SimpleNamespace(id=2,customer_id=3),
            query="Công thay bộ nhông sên dĩa giá bao nhiêu?",job_key="service-price-only")

    assert "180.000 đồng/lần" in result.prompt
    assert "lịch trống" not in result.prompt
    assert "ngày và giờ nào" not in result.prompt
    model.assert_not_called()


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
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.services.auto_reply_service._notify_rag_handoff_required'):
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
    assert 'thời hạn hoặc điều kiện bảo hành' in result.prompt
    assert 'không có bảo hành' not in result.prompt
    assert conversation.bot_mode=='auto'
    assert notify.call_args.kwargs['reason']=='business_decision_needed'


@pytest.mark.parametrize(
    ("query", "expected_topic"),
    [
        ("Phí giao hàng và thời gian giao đến nhà tôi là bao nhiêu?", "phí giao hàng hoặc thời gian giao"),
        ("Shop cho đổi trả trong trường hợp nào?", "điều kiện đổi trả hoặc hoàn tiền"),
        ("Mã này có lắp vừa xe Vision 2023 không?", "khả năng tương thích với xe hoặc thiết bị của bạn"),
        ("Bảo hành sản phẩm trong bao lâu?", "thời hạn hoặc điều kiện bảo hành"),
    ],
)
def test_missing_evidence_reply_names_unconfirmed_detail_without_inventing_policy(query, expected_topic):
    answer = _missing_evidence_reply(query, reply_language="vi")

    assert expected_topic in answer
    assert "nguồn hiện có" in answer.lower()
    assert "nhân viên kiểm tra" in answer
    assert not any(claim in answer for claim in ("miễn phí giao hàng", "được đổi trả", "chắc chắn lắp vừa", "bảo hành trọn đời"))


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


@pytest.mark.parametrize(
    ("query", "evidence_text", "unsafe_answer", "repaired_answer"),
    [
        (
            "Chính sách hiện có xác nhận bảo hành trọn đời không?",
            "Chính sách hiện có không đề cập thời hạn bảo hành.",
            "Chúng tôi không cung cấp bảo hành trọn đời cho sản phẩm.",
            "Chính sách chưa đề cập thời hạn bảo hành; shop cần xác minh thêm.",
        ),
        (
            "Chính sách hiện có xác nhận bảo hành trọn đời không?",
            "Chính sách hiện có không đề cập thời hạn bảo hành.",
            "Chính sách hiện có không đề cập thời hạn bảo hành, vì vậy không có bảo hành trọn đời.",
            "Chính sách chưa đề cập thời hạn bảo hành; shop cần xác minh thêm.",
        ),
        (
            "What return period applies to eligible items?",
            "Only eligible items may be requested for exchange within seven days after receipt.",
            "You may exchange the item within seven days after receipt.",
            "Eligible items may be requested for exchange within seven days after receipt.",
        ),
    ],
)
def test_policy_guard_rejection_gets_one_graph_retry_and_repairs_unsafe_claim(
    query, evidence_text, unsafe_answer, repaired_answer
):
    evidence = SimpleNamespace(content=evidence_text, document_id=17, metadata={})
    with patch("app.services.conversation_graph.call_llm", side_effect=[
        json.dumps({"answer": unsafe_answer, "sources": [1]}),
        json.dumps({"answer": repaired_answer, "sources": [1]}),
    ]) as model, patch("app.services.quota_service.record_quota_usage"), patch(
        "app.rag.serving.retrieve_shop_knowledge", return_value=[evidence]
    ), patch("app.services.auto_reply_service._notify_rag_handoff_required") as notify:
        result = graph_reply(
            DB(), business_id=1, conversation=SimpleNamespace(id=2, customer_id=3),
            query=query, job_key="policy-claim-repair",
        )

    assert result.status == "graph_answer"
    assert repaired_answer in result.prompt
    assert unsafe_answer not in result.prompt
    assert model.call_count == 2
    assert "previous draft failed source or arithmetic validation" in model.call_args_list[1].args[0][-2]["content"]
    notify.assert_not_called()


@pytest.mark.parametrize(
    ("query", "evidence_text", "unsafe_answer"),
    [
        (
            "Chính sách hiện có xác nhận bảo hành trọn đời không?",
            "Chính sách hiện có không đề cập thời hạn bảo hành.",
            "Chúng tôi không cung cấp bảo hành trọn đời cho sản phẩm.",
        ),
        (
            "Chính sách hiện có xác nhận bảo hành trọn đời không?",
            "Chính sách hiện có không đề cập thời hạn bảo hành.",
            "Chính sách hiện có không đề cập thời hạn bảo hành, vì vậy không có bảo hành trọn đời.",
        ),
        (
            "What return period applies to eligible items?",
            "Only eligible items may be requested for exchange within seven days after receipt.",
            "You may exchange the item within seven days after receipt.",
        ),
    ],
)
def test_repeated_policy_guard_rejection_uses_safe_fallback_and_notifies_staff(
    query, evidence_text, unsafe_answer
):
    evidence = SimpleNamespace(content=evidence_text, document_id=18, metadata={})
    with patch("app.services.conversation_graph.call_llm", side_effect=[
        json.dumps({"answer": unsafe_answer, "sources": [1]}),
        json.dumps({"answer": unsafe_answer, "sources": [1]}),
    ]) as model, patch("app.services.quota_service.record_quota_usage"), patch(
        "app.rag.serving.retrieve_shop_knowledge", return_value=[evidence]
    ), patch("app.services.auto_reply_service._notify_rag_handoff_required") as notify:
        result = graph_reply(
            DB(), business_id=1, conversation=SimpleNamespace(id=2, customer_id=3),
            query=query, job_key="policy-claim-safe-fallback",
        )

    assert result.status == "graph_answer"
    assert unsafe_answer not in result.prompt
    assert "nhân viên kiểm tra" in result.prompt.lower()
    assert model.call_count == 2
    notify.assert_called_once()


def test_notification_persistence_failure_keeps_guarded_fallback_and_marks_handoff_unpersisted(caplog):
    evidence = SimpleNamespace(
        content="Sản phẩm đủ điều kiện được yêu cầu đổi trong 7 ngày kể từ khi nhận hàng.",
        document_id=181,
        metadata={},
    )
    db = DB()
    rollbacks = []
    db.rollback = lambda: rollbacks.append(True)
    with patch("app.services.conversation_graph.call_llm", side_effect=[
        '{"mode":"answer","tools":["knowledge"]}',
        '{"answer":"Bạn có thể đổi hàng trong 7 ngày.","sources":[1]}',
        '{"answer":"Bạn có thể đổi hàng trong 7 ngày.","sources":[1]}',
    ]) as model, patch("app.services.quota_service.record_quota_usage"), patch(
        "app.rag.serving.retrieve_shop_knowledge", return_value=[evidence]
    ), patch(
        "app.services.auto_reply_service._notify_rag_handoff_required",
        side_effect=RuntimeError("synthetic notification storage failure"),
    ):
        result = graph_reply(
            db,
            business_id=1,
            conversation=SimpleNamespace(id=2, customer_id=3, business_id=1),
            query="Tôi có thể đổi hàng trong bao lâu?",
            job_key="notification-failure-safe-fallback",
        )

    assert result.status == "graph_answer"
    assert "nhân viên kiểm tra" in result.prompt.lower()
    assert result.metadata["staff_handoff"] == {
        "requested": True,
        "reason": "business_decision_needed",
        "persisted": False,
    }
    assert model.call_count == 2
    assert rollbacks == [True]
    assert "Could not persist RAG handoff: error_type=RuntimeError" in caplog.text


def test_mixed_product_price_and_policy_question_retrieves_both_authoritative_sources(
    monkeypatch, tmp_path
):
    from app.rag import run_logger

    monkeypatch.setattr(run_logger, "_log_path", lambda: tmp_path / "mixed-source.jsonl")
    item = {
        "ref": "product:123", "name": "Alpha", "sku": "SYNTH-ALPHA",
        "kind": "goods", "price": "180000", "billing_unit": None,
        "available": 3, "description": "Synthetic catalog item",
    }
    policy = SimpleNamespace(
        content="Sản phẩm đủ điều kiện mới được yêu cầu đổi trong 7 ngày kể từ khi nhận hàng.",
        document_id=19,
        metadata={"synthetic_evidence_id": "policy:return-v1"},
    )
    answer = {
        # graph_json_completion adds these two server-side fields after the
        # provider returns the strict ShopAnswer claims schema.
        "answer": "Alpha có giá 180.000 đồng. Sản phẩm đủ điều kiện có thể được yêu cầu đổi trong 7 ngày kể từ khi nhận hàng.",
        "sources": [1, 2],
        "claims": [
            {"text": "Alpha có giá 180.000 đồng.", "sources": [1], "offering_refs": ["product:123"]},
            {"text": "Sản phẩm đủ điều kiện có thể được yêu cầu đổi trong 7 ngày kể từ khi nhận hàng.",
             "sources": [2], "offering_refs": []},
        ],
        "calculation": None,
        "needs_staff_decision": False,
    }
    query = "Alpha giá bao nhiêu và có áp dụng đổi trong 7 ngày không?"
    with patch("app.services.conversation_graph.call_llm", return_value=json.dumps(answer)) as model, \
         patch("app.services.quota_service.record_quota_usage"), \
         patch("app.services.business_request.current_offerings", return_value=[item]) as catalog, \
         patch("app.services.business_request.get_current_offering", return_value=item), \
         patch("app.rag.serving.retrieve_shop_knowledge", return_value=[policy]) as knowledge, \
         patch("app.services.auto_reply_service._deterministic_customer_reply", return_value=None):
        result = graph_reply(
            DB(), business_id=1, conversation=SimpleNamespace(id=2, customer_id=3),
            query=query, job_key="mixed-catalog-policy",
        )

    assert result.status == "graph_answer"
    assert "180.000" in result.prompt or "180,000" in result.prompt
    assert "đủ điều kiện" in result.prompt.lower()
    catalog.assert_called_once()
    knowledge.assert_called_once()
    context = model.call_args.args[0][-1]["content"]
    assert "CURRENT_CRM_CATALOG" in context and "Alpha" in context and "180.000" in context
    assert "Sản phẩm đủ điều kiện" in context
    assert "Return exactly the shop_answer schema" in context
    assert "Return JSON with answer and sources" not in context
    import json as _json
    records = [
        _json.loads(line)
        for line in (tmp_path / "mixed-source.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    run_record = next(record for record in records if record["operation"] == "conversation_graph")
    assert run_record["tools"] == ["catalog", "knowledge"]
    assert run_record["catalog_evidence_item_count"] == 1
    assert len(run_record["evidence_manifest"]) >= 2


def test_provider_structured_output_failure_returns_safe_answer_without_retry(monkeypatch, tmp_path):
    from app.rag import run_logger

    monkeypatch.setattr(run_logger, "_log_path", lambda: tmp_path / "provider-error.jsonl")

    class BadRequestError(Exception):
        status_code = 400

    policy = SimpleNamespace(
        content="Sản phẩm đủ điều kiện mới được yêu cầu đổi trong 7 ngày kể từ khi nhận hàng.",
        document_id=20,
        metadata={},
    )
    with patch("app.services.conversation_graph.call_llm", side_effect=BadRequestError("provider detail hidden")) as model, \
         patch("app.services.quota_service.record_quota_usage"), \
         patch("app.rag.serving.retrieve_shop_knowledge", return_value=[policy]), \
         patch("app.services.auto_reply_service._notify_rag_handoff_required") as notify:
        result = graph_reply(
            DB(), business_id=1, conversation=SimpleNamespace(id=2, customer_id=3),
            query="What is the exchange policy?", job_key="structured-provider-error",
        )

    assert result.status == "graph_answer"
    assert "verify" in result.prompt.lower() or "kiểm tra" in result.prompt.lower()
    assert "provider detail hidden" not in result.prompt
    assert model.call_count == 1
    notify.assert_called_once()
    import json as _json
    records = [
        _json.loads(line)
        for line in (tmp_path / "provider-error.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    run_record = next(record for record in records if record["operation"] == "conversation_graph")
    assert run_record["answer_generation_status"] == "provider_error_safe_fallback"
    assert run_record["answer_provider_status_code"] == 400


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
