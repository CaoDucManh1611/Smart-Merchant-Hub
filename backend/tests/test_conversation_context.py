import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models import BusinessSetting, Conversation, Customer, CustomerFact
from app.models.customer_collection import CustomerConsent
from app.models.recommendation import RecommendationRequest
from app.models.sales import Order, OrderItem, Product
from app.services.conversation_context import customer_memory, recommendation_evidence, evidence_manifest
from app.services.conversation_graph import graph_reply, parse_plan


def grant(db, conv):
    db.add(CustomerConsent(business_id=1,customer_id=conv.customer_id,purpose='personalization',status='granted'))
    db.commit()


def test_memory_is_opt_in_and_never_crosses_tenants(setup):
    db,conv,*_=setup
    db.add(CustomerFact(business_id=1,customer_id=conv.customer_id,fact_type='preference',fact_key='color',fact_value_json='blue',is_verified=True))
    db.commit()
    assert customer_memory(db,1,conv.customer_id)['facts']==[]
    grant(db,conv)
    with patch('app.services.conversation_context.get_customer_fact_extraction_enabled',return_value=True):
        assert customer_memory(db,1,conv.customer_id)['facts'][0]['value']=='blue'
        assert customer_memory(db,2,conv.customer_id)['facts']==[]
        conv.customer.fact_extraction_opt_out=True;db.commit()
        assert customer_memory(db,1,conv.customer_id)['facts']==[]


def test_memory_expiry_confidence_latest_value_and_revocation(setup):
    db,conv,*_=setup;grant(db,conv)
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    for key,value,confidence,expires in [('color','old',.9,None),('color','new',.9,None),('secret','expired',1,now-timedelta(days=1)),('guess','uncertain',.2,None)]:
        db.add(CustomerFact(business_id=1,customer_id=conv.customer_id,fact_type='preference',fact_key=key,fact_value_json=value,confidence=confidence,valid_until=expires))
    db.commit()
    with patch('app.services.conversation_context.get_customer_fact_extraction_enabled',return_value=True):
        assert [f['value'] for f in customer_memory(db,1,conv.customer_id)['facts']]==['new']
        db.add(CustomerConsent(business_id=1,customer_id=conv.customer_id,purpose='personalization',status='revoked'));db.commit()
        assert customer_memory(db,1,conv.customer_id)['facts']==[]


def test_ranker_observes_current_stock_price_and_deleted_catalog(setup):
    db,conv,goods,rental,*_=setup
    ranked=recommendation_evidence(db,1,conv,'TEST-GOODS')
    assert [i['product_id'] for i in ranked['items']]==[goods.id]
    assert ranked['items'][0]['price']==200000
    goods.price=250000;db.commit()
    assert recommendation_evidence(db,1,conv,'TEST-GOODS')['items'][0]['price']==250000
    goods.reserved_quantity=goods.stock_quantity;db.commit()
    assert recommendation_evidence(db,1,conv,'TEST-GOODS')['items']==[]
    goods.reserved_quantity=0;goods.status='inactive';db.commit()
    assert recommendation_evidence(db,1,conv,'TEST-GOODS')['items']==[]
    assert all(i['sku']!='PRIVATE' for i in recommendation_evidence(db,1,conv,'gợi ý')['items'])


def test_recommendation_tool_uses_ranker_memory_catalog_and_persists_trace(setup):
    db,conv,goods,*_=setup
    responses=[json.dumps({'mode':'answer','tools':['recommendations'],'recommendation_query':'TEST-GOODS'}),json.dumps({'answer':'Mình gợi ý Hàng thử, giá 200.000 đồng.','sources':[1,3]})]
    retrieved_chunk=SimpleNamespace(
        chunk_id=101,
        document_id=201,
        content='Hàng thử là sản phẩm thử nghiệm của shop.',
        metadata={'product_id':goods.id},
        retrieval_scores={'bm25_score':0.8,'bm25_rank':1},
    )
    with patch('app.services.conversation_graph.call_llm',side_effect=responses) as model,patch('app.services.quota_service.record_quota_usage'),patch('app.rag.answer_guard.has_valid_citations',return_value=True),patch('app.rag.retriever.retrieve',return_value=[retrieved_chunk]),patch('app.services.auto_reply_service._deterministic_customer_reply',return_value=None):
        result=graph_reply(db,business_id=1,conversation=conv,query='Gợi ý Hàng thử cho mình',job_key='context-test')
    assert result.metadata['recommendation']['request_id']
    # Product advice is rendered deterministically from the ranked, live
    # catalog candidates; the graph should not make a second LLM call that
    # could rewrite current price or availability.
    assert 'Hàng thử' in result.prompt and '200.000' in result.prompt
    model.assert_not_called()
    request=db.query(RecommendationRequest).filter_by(request_id=result.metadata['recommendation']['request_id']).one()
    assert request.context['surface']=='conversation_graph'
    assert request.context['retrieval_trace']


def test_case_002_budget_recommendation_survives_read_only_synthetic_graph(tmp_path):
    from pathlib import Path
    from scripts.rag_synthetic_context_factory import synthetic_context

    cases_path = Path(__file__).parents[1] / 'test_data' / 'rag_answer_quality_acceptance_v1.jsonl'
    case = next(json.loads(line) for line in cases_path.read_text(encoding='utf-8').splitlines()
                if 'answer-002-budget' in line)
    context = synthetic_context(case)
    db, conv = context.db, context.conversation
    assert db.get_bind().dialect.name == "sqlite"
    db.connection().exec_driver_sql("PRAGMA query_only=ON")
    query = "Tôi có tối đa 200.000 đồng, có sản phẩm nào phù hợp?"

    try:
        with patch('app.services.conversation_graph.call_llm', return_value=json.dumps({
            'mode': 'answer', 'tools': ['recommendations'],
        })), patch('app.services.quota_service.record_quota_usage'), \
             patch('app.rag.serving.retrieve_shop_knowledge', return_value=[]), \
             patch('app.services.auto_reply_service._deterministic_customer_reply', return_value=None), \
             patch('app.rag.run_logger._log_path', return_value=tmp_path / 'rag.jsonl'):
            result = graph_reply(
                db, business_id=context.business_id, conversation=conv, query=query,
                job_key='read-only-budget-recommendation',
            )

        assert result.status == 'graph_answer'
        assert 'Alpha' in result.prompt
        assert '180.000' in result.prompt
        assert 'Beta' not in result.prompt
        assert 'tương thích' not in result.prompt.casefold()
        assert db.query(RecommendationRequest).count() == 0
        assert result.metadata['recommendation']['rfm_ranking']['applied'] is False
        assert db.connection().exec_driver_sql('PRAGMA query_only').scalar() == 1
    finally:
        db.close()


def test_graph_rfm_recommendations_respect_five_synthetic_customer_personas(setup, monkeypatch, tmp_path):
    from app.services import recommendation_service

    db, base_conversation, _goods, _rental, _service, foreign_product = setup
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    monkeypatch.setattr(recommendation_service, "_now", lambda: now)

    db.add(BusinessSetting(
        business_id=1, key="customer_fact_extraction_enabled", value="true",
    ))
    alpha = Product(
        business_id=1, name="Áo mẫu Alpha", sku="SYN-ALPHA", price=180000,
        stock_quantity=3, status="active", metadata_={"offering_type": "goods", "category": "ao"},
    )
    beta = Product(
        business_id=1, name="Áo mẫu Beta", sku="SYN-BETA", price=190000,
        stock_quantity=4, status="active", metadata_={"offering_type": "goods", "category": "ao"},
    )
    over_budget = Product(
        business_id=1, name="Áo mẫu Gamma", sku="SYN-GAMMA", price=250000,
        stock_quantity=9, status="active", metadata_={"offering_type": "goods", "category": "ao"},
    )
    db.add_all([alpha, beta, over_budget])
    db.flush()

    personas = {
        "new": (base_conversation.customer, base_conversation, 0, 0),
    }
    for key in ("frequent", "high_value", "no_consent", "revoked"):
        customer = Customer(
            business_id=1, channel="telegram", external_user_id=f"synthetic-{key}",
            name=f"Synthetic {key}", fact_extraction_opt_out=False, status="active",
        )
        db.add(customer)
        db.flush()
        conversation = Conversation(
            business_id=1, customer_id=customer.id, channel="telegram", status="open",
            bot_mode="auto", priority="normal",
        )
        db.add(conversation)
        db.flush()
        expected_frequency = 4 if key == "frequent" else 2 if key == "high_value" else 3
        expected_monetary = 4 * 50000 if key == "frequent" else 2 * 300000 if key == "high_value" else 3 * 100000
        personas[key] = (customer, conversation, expected_frequency, expected_monetary)

    for key in ("frequent", "high_value"):
        customer = personas[key][0]
        db.add(CustomerConsent(
            business_id=1, customer_id=customer.id, purpose="personalization", status="granted",
        ))
    revoked_customer = personas["revoked"][0]
    db.add_all([
        CustomerConsent(business_id=1, customer_id=revoked_customer.id,
                        purpose="personalization", status="granted"),
        CustomerConsent(business_id=1, customer_id=revoked_customer.id,
                        purpose="personalization", status="revoked"),
    ])
    db.flush()

    order_number = 0
    for key in ("frequent", "high_value", "no_consent", "revoked"):
        customer, _conversation, count, total = personas[key]
        for index in range(count):
            order_number += 1
            amount = total // count
            order = Order(
                business_id=1, customer_id=customer.id,
                order_number=f"SYN-RFM-{order_number}", status="completed",
                payment_status="paid", total_amount=Decimal(amount),
                created_at=now - timedelta(days=45 + index), updated_at=now,
            )
            db.add(order)
            db.flush()
            db.add(OrderItem(
                order_id=order.id, product_id=alpha.id, quantity=1,
                unit_price=Decimal(amount), line_total=Decimal(amount),
                product_name_snapshot=alpha.name, sku_snapshot=alpha.sku,
            ))

    foreign_customer = Customer(
        business_id=2, channel="telegram", external_user_id="synthetic-foreign",
        fact_extraction_opt_out=False, status="active",
    )
    db.add(foreign_customer)
    db.flush()
    foreign_order = Order(
        business_id=2, customer_id=foreign_customer.id, order_number="SYN-FOREIGN-1",
        status="completed", payment_status="paid", total_amount=Decimal("1"),
        created_at=now - timedelta(days=45), updated_at=now,
    )
    db.add(foreign_order)
    db.flush()
    db.add(OrderItem(
        order_id=foreign_order.id, product_id=foreign_product.id, quantity=1,
        unit_price=Decimal("1"), line_total=Decimal("1"),
        product_name_snapshot=foreign_product.name, sku_snapshot=foreign_product.sku,
    ))
    db.commit()

    query = "Tôi có tối đa 200.000 đồng, có sản phẩm nào phù hợp?"
    for key, (customer, conversation, expected_frequency, expected_monetary) in personas.items():
        log_path = tmp_path / f"{key}.jsonl"
        with patch("app.services.conversation_graph.call_llm", return_value=json.dumps({
            "mode": "answer", "tools": ["recommendations", "catalog"],
        })), patch("app.services.quota_service.record_quota_usage"), \
             patch("app.rag.serving.retrieve_shop_knowledge", return_value=[]), \
             patch("app.services.auto_reply_service._deterministic_customer_reply", return_value=None), \
             patch("app.services.conversation_context.approved_reply_style", return_value=None), \
             patch("app.rag.run_logger._log_path", return_value=log_path):
            result = graph_reply(
                db, business_id=1, conversation=conversation, query=query,
                job_key=f"synthetic-rfm-{key}",
            )

        assert result.status == "graph_answer", key
        assert "Áo mẫu" in result.prompt, (key, result.prompt)
        assert "250.000" not in result.prompt, (key, result.prompt)
        assert "Không được đọc" not in result.prompt and "PRIVATE" not in result.prompt
        request_id = result.metadata["recommendation"]["request_id"]
        request = db.query(RecommendationRequest).filter_by(
            business_id=1, request_id=request_id,
        ).one()
        assert all(item["product_id"] != foreign_product.id for item in request.served_items), key
        assert all(item["price"] <= 200000 for item in request.served_items), key

        if key in {"frequent", "high_value"}:
            assert request.customer_id == customer.id
            assert request.context["rfm_ranker_applied"] is True
            assert request.context["personalization_applied"] is True
            assert request.context["rfm_snapshot"]["frequency"] == expected_frequency
            assert request.context["rfm_snapshot"]["monetary"] == expected_monetary
            assert "rfm_segment" in request.context["personalization_signals"]
            assert result.metadata["recommendation"]["rfm_ranking"]["weighting_applied"] is True
            assert request.context["query"] == query
        else:
            # New/never-consented/revoked customers may have no RFM snapshot or
            # purchase-history influence, even when synthetic orders exist.
            assert request.customer_id is None, key
            assert "rfm_snapshot" not in request.context, key
            assert request.context["rfm_ranker_applied"] is False, key
            assert request.context["personalization_applied"] is False, key
            assert request.context["personalization_signals"] == [], key
            assert result.metadata["recommendation"]["rfm_ranking"]["weighting_applied"] is False
            assert request.context["query"] == ""
        assert "xác suất mua" not in result.prompt.casefold()
        assert "probability" not in result.prompt.casefold()


def test_manifest_records_changes_without_customer_content():
    first=evidence_manifest(['CURRENT_CUSTOMER_MEMORY: private customer information'])
    assert 'private' not in str(first)
    assert first!=evidence_manifest(['CURRENT_CUSTOMER_MEMORY: changed'])


def test_plan_recommendation_query_is_bounded():
    assert parse_plan('{"mode":"answer","tools":["recommendations"],"recommendation_query":"màu xanh"}')['recommendation_query']=='màu xanh'
    with pytest.raises(ValueError):parse_plan(json.dumps({'mode':'answer','tools':['recommendations'],'recommendation_query':'x'*1001}))


def test_style_learning_requires_consent_and_approved_policy(setup):
    from test_chatbot_bandit_runtime import _runtime_policy
    from app.services.conversation_context import approved_reply_style
    from app.models.experimentation import BanditDecision
    db,conv,*_=setup
    _runtime_policy(db,1);db.commit()
    with patch('app.services.conversation_context.get_customer_fact_extraction_enabled',return_value=True):
        assert approved_reply_style(db,1,conv,'tư vấn','one') is None
        assert db.query(BanditDecision).count()==0
        grant(db,conv)
        first=approved_reply_style(db,1,conv,'tư vấn','one')
        assert first is not None
        second=approved_reply_style(db,1,conv,'tư vấn','one')
        assert first.decision_id==second.decision_id
        assert db.query(BanditDecision).one().selection_reason=='warmup_default'
        assert first.arm=='control'


def test_segmentation_keeps_rules_when_no_training_sample(setup):
    from app.models.recommendation import RecommendationTrainingRun
    from app.services.recommendation_service import train_customer_segments
    db,conv,*_=setup
    run=RecommendationTrainingRun(business_id=1,status='queued',algorithm='deterministic_rfm_kmeans')
    db.add(run);db.commit()
    trained=train_customer_segments(db,business_id=1,training_run_id=run.id)
    assert trained.status=='succeeded'
    assert trained.metrics['learning_ready'] is False
    assert trained.metrics['clusters']==0


def test_tool_named_mode_normalizes_without_broadening_permissions():
    assert parse_plan('{"mode":"recommendations","tools":["recommendations"]}') == {"mode":"answer","tools":["recommendations"]}
    with pytest.raises(ValueError):parse_plan('{"mode":"execute_sql","tools":["execute_sql"]}')
