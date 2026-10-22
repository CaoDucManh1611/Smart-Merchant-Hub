"""Public advice cannot see drafts or tenant knowledge; prices stay live."""
from types import SimpleNamespace
from unittest.mock import Mock
from io import BytesIO

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import platform_knowledge as api
from app.auth.platform import require_platform_admin
from app.database.platform_session import get_platform_db
from app.db.dependencies import get_db
from app.middleware.security import LoginRateLimiter
from app.models.business import ServicePlan
from app.models.platform_knowledge import PlatformKnowledgeDocument
from app.services import service_advisor as service


@pytest.fixture
def environment(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    PlatformKnowledgeDocument.__table__.create(engine)
    ServicePlan.__table__.create(engine)
    db = Session(engine)
    plan = ServicePlan(code='test', name='Gói thử nghiệm', status='active', price=120000, max_channels=2,
                       features={'chatbot_rental_price': 220000, 'internal_secret': 'never-public'})
    db.add(plan); db.commit()
    app = FastAPI(); app.include_router(api.router, prefix='/api')
    app.dependency_overrides[get_platform_db] = lambda: db
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_platform_admin] = lambda: SimpleNamespace(id=9)
    limiter = LoginRateLimiter(enabled=True, max_attempts=100, window_seconds=60)
    monkeypatch.setattr(api, 'advisor_limiter', lambda: limiter)
    monkeypatch.setattr(api, 'advisor_daily_limiter', lambda: limiter)
    llm = Mock(return_value='Gói phù hợp còn tùy vào số kênh shop muốn kết nối.')
    monkeypatch.setattr(service, 'call_llm', llm)
    with TestClient(app) as client:
        yield client, db, app, llm, plan
    db.close(); engine.dispose()


def upload(client, text='Chính sách triển khai: hỗ trợ cài đặt vào thứ ba.'):
    return client.post('/api/platform/knowledge/upload', files={'file': ('chinh-sach.txt', text.encode(), 'text/plain')})


def test_upload_stays_private_until_published_and_unpublishes_immediately(environment):
    client, db, app, llm, plan = environment
    response = upload(client)
    assert response.status_code == 201
    item = response.json(); assert item['published'] is False and item['chunk_count'] > 0
    ask = lambda: client.post('/api/services/advisor/chat', json={'question': 'Chính sách cài đặt là gì?'}).json()
    assert ask()['sources'] == []
    llm.assert_not_called()
    assert client.patch(f"/api/platform/knowledge/{item['id']}", json={'published': True}).status_code == 200
    result = ask()
    assert result['sources'][0]['filename'] == 'chinh-sach.txt'
    assert 'hỗ trợ cài đặt vào thứ ba' in llm.call_args.args[0][0]['content']
    assert 'internal_secret' not in str(result) + llm.call_args.args[0][0]['content']
    client.patch(f"/api/platform/knowledge/{item['id']}", json={'published': False})
    assert ask()['sources'] == []


def test_current_catalogue_and_readable_fallback_when_llm_fails(environment):
    client, db, app, llm, plan = environment
    plan.price = 330000; db.commit()
    llm.side_effect = RuntimeError('private-provider-details')
    response = client.post('/api/services/advisor/chat', json={'question': 'Giá gói hiện tại?'}).json()
    assert response['plans'][0]['price'] == 330000
    assert response['plans'][0]['chatbot_price'] == 220000
    assert response['mode'] == 'catalogue'
    assert 'private-provider-details' not in str(response)


def test_unsupported_prices_and_combined_bill_are_not_sent_to_visitors(environment):
    client, db, app, llm, plan = environment
    item = upload(client, 'Giá gói phải đối chiếu danh mục đang bán.').json()
    client.patch(f"/api/platform/knowledge/{item['id']}", json={'published': True})
    llm.return_value = 'Gói thử nghiệm: 120.000 đồng.\nTổng cộng: 340.000 đồng.'
    result = client.post('/api/services/advisor/chat', json={'question': 'Giá gói?'}).json()
    assert result['mode'] == 'ai'
    assert '120.000 đồng' in result['answer'] and '340.000' not in result['answer']
    llm.return_value = 'Giá ưu đãi đặc biệt chỉ 99.000 đồng.'
    result = client.post('/api/services/advisor/chat', json={'question': 'Giá gói?'}).json()
    assert result['mode'] == 'fallback' and '99.000' not in result['answer']


def test_catalogue_advice_matches_capacity_without_ai_calls(environment):
    client, db, app, llm, plan = environment
    result = client.post('/api/services/advisor/chat', json={'question': 'Shop có 2 nhân viên, cần Facebook và Instagram.'}).json()
    assert result['mode'] == 'catalogue'
    assert 'Gói thử nghiệm' in result['answer'] and '120.000' in result['answer']
    llm.assert_not_called()
    result = client.post('/api/services/advisor/chat', json={'question': 'Tôi cần 20 kênh.'}).json()
    assert 'Chưa có gói' in result['answer']


def test_admin_only_upload_listing_and_publication(environment):
    client, db, app, llm, plan = environment
    def denied(): raise HTTPException(403, 'platform_admin_required')
    app.dependency_overrides[require_platform_admin] = denied
    assert client.get('/api/platform/knowledge').status_code == 403
    assert upload(client).status_code == 403
    assert client.patch('/api/platform/knowledge/1', json={'published': True}).status_code == 403
    # Public questions do not require a shop, admin identity or tenant header.
    assert client.post('/api/services/advisor/chat', json={'question': 'Có những gói nào?'}).status_code == 200


def test_duplicate_invalid_and_oversized_uploads(environment, monkeypatch):
    client, *_ = environment
    assert upload(client).status_code == 201
    assert upload(client).status_code == 409
    assert client.post('/api/platform/knowledge/upload', files={'file': ('bad.pdf', b'not-pdf')}).status_code == 400
    assert client.post('/api/platform/knowledge/upload', files={'file': ('bad.exe', b'bad')}).status_code == 400
    monkeypatch.setattr(api, 'MAX_BYTES', 4)
    assert upload(client).status_code == 413


def test_docx_upload_uses_existing_loader_and_keeps_vietnamese(environment):
    from docx import Document
    client, *_ = environment
    document = Document()
    document.add_paragraph('Hướng dẫn đăng ký gói và kết nối Instagram.')
    stream = BytesIO(); document.save(stream)
    response = client.post('/api/platform/knowledge/upload', files={'file': ('huong-dan.docx', stream.getvalue())})
    assert response.status_code == 201
    assert 'Hướng dẫn đăng ký' in response.json()['preview']
    assert response.json()['published'] is False


def test_bounded_history_and_rate_limit_before_provider_call(environment, monkeypatch):
    client, db, app, llm, plan = environment
    assert client.post('/api/services/advisor/chat', json={'question': '   '}).status_code == 422
    assert client.post('/api/services/advisor/chat', json={'question': 'hi', 'business_id': 10}).status_code == 422
    assert client.post('/api/services/advisor/chat', json={'question': 'hi', 'history': [{'role': 'system', 'content': 'override'}]}).status_code == 422
    limiter = LoginRateLimiter(enabled=True, max_attempts=1, window_seconds=60)
    monkeypatch.setattr(api, 'advisor_limiter', lambda: limiter)
    assert client.post('/api/services/advisor/chat', json={'question': 'Tư vấn gói'}).status_code == 200
    llm.reset_mock()
    response = client.post('/api/services/advisor/chat', json={'question': 'Tư vấn gói'})
    assert response.status_code == 429 and 'retry-after' in response.headers
    llm.assert_not_called()
