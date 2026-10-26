import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models import CustomerFact
from app.models.customer_collection import CustomerConsent
from app.models.recommendation import RecommendationRequest
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
    with patch('app.services.conversation_graph.call_llm',side_effect=responses) as model,patch('app.services.quota_service.record_quota_usage'),patch('app.rag.answer_guard.has_valid_citations',return_value=True):
        result=graph_reply(db,business_id=1,conversation=conv,query='Tư vấn cho mình',job_key='context-test')
    assert result.metadata['recommendation']['request_id']
    prompt=model.call_args.args[0][-1]['content']
    assert 'CURRENT_RECOMMENDATIONS' in prompt and 'CURRENT_CRM_CATALOG' in prompt and 'CURRENT_CUSTOMER_MEMORY' in prompt
    assert 'PRIVATE' not in prompt
    request=db.query(RecommendationRequest).filter_by(request_id=result.metadata['recommendation']['request_id']).one()
    assert request.context['surface']=='conversation_graph'


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
