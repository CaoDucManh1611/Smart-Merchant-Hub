from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.platform_team import router
from app.auth.dependencies import get_current_user
from app.auth.platform import require_platform_admin
from app.db.dependencies import get_db
from app.models.business import Business, User
from app.models.saas import PlatformMembership
from app.models.auth_session import AuthSession
from app.models.platform_staff_audit import PlatformStaffAudit
from app.auth.passwords import verify_password


@pytest.fixture
def environment():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    for model in (Business, User, PlatformMembership, AuthSession, PlatformStaffAudit):
        model.__table__.create(engine)
    db = Session(engine)
    for index, role in enumerate(('owner', 'content', 'viewer', 'custom'), 1):
        db.add(User(id=index, full_name=f'Admin {index}', email=f'admin{index}@example.test', role='platform_staff', is_active=True))
        db.add(PlatformMembership(user_id=index, platform_role=role, platform_permissions=['backups.read'] if role == 'custom' else [], is_active=True))
    db.add(User(id=5, full_name='Shop user', email='shop@example.test', role='business_admin', is_active=True))
    db.commit()
    if db.bind.dialect.name == 'postgresql':
        db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), 6, false)"))
        db.commit()
    current = SimpleNamespace(id=1)
    app = FastAPI(); app.include_router(router, prefix='/api')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, current.id)
    for path, method in [('/platform/shops', 'GET'), ('/platform/knowledge/upload', 'POST'),
                         ('/platform/knowledge', 'GET'), ('/platform/backups', 'GET'),
                         ('/platform/backups/fake/download', 'GET'), ('/platform/backups/fake/restore', 'POST'),
                         ('/platform/new-sensitive-endpoint', 'GET')]:
        app.add_api_route('/api' + path, lambda: {'ok': True}, methods=[method], dependencies=[Depends(require_platform_admin)])
    with TestClient(app) as client:
        yield client, db, current
    db.close(); engine.dispose()


def test_platform_membership_does_not_grant_all_admin_actions(environment):
    client, db, current = environment
    current.id = 2
    access = client.get('/api/platform/access')
    assert access.status_code == 200 and access.json()['role'] == 'content'
    assert client.get('/api/platform/knowledge').status_code == 200
    assert client.post('/api/platform/knowledge/upload').status_code == 200
    assert client.get('/api/platform/shops').status_code == 403
    assert client.get('/api/platform/team').status_code == 403
    assert client.get('/api/platform/new-sensitive-endpoint').status_code == 403
    current.id = 5
    assert client.get('/api/platform/access').status_code == 403


def test_viewer_cannot_write_and_backup_read_is_not_download_or_restore(environment):
    client, db, current = environment
    current.id = 3
    assert client.get('/api/platform/knowledge').status_code == 200
    assert client.post('/api/platform/knowledge/upload').status_code == 403
    current.id = 4
    assert client.get('/api/platform/backups').status_code == 200
    assert client.get('/api/platform/backups/fake/download').status_code == 403
    assert client.post('/api/platform/backups/fake/restore').status_code == 403


def test_owner_creates_separate_internal_identity_and_redacts_password(environment):
    client, db, current = environment
    payload = {'full_name': 'New staff', 'email': 'internal@example.test', 'password': 'Strong-test-Password12!', 'role': 'support'}
    response = client.post('/api/platform/team', json=payload)
    assert response.status_code == 201
    assert 'password' not in response.text
    row = db.get(User, response.json()['user_id'])
    assert row.business_id is None and verify_password(payload['password'], row.password_hash)
    member = db.scalar(select(PlatformMembership).where(PlatformMembership.user_id == row.id))
    assert member.platform_role == 'support'
    assert '*' not in response.json()['permissions']
    assert client.post('/api/platform/team', json=payload).status_code == 409
    current.id = row.id
    assert client.post('/api/platform/team', json={**payload, 'email': 'escalate@example.test', 'role': 'owner'}).status_code == 403


def test_update_revokes_sessions_audits_changes_and_cannot_lock_self(environment):
    client, db, current = environment
    session = AuthSession(user_id=2, token_hash='test-session-hash', expires_at=datetime.now()+timedelta(days=1))
    db.add(session); db.commit()
    response = client.patch('/api/platform/team/2', json={'role': 'custom', 'permissions': ['knowledge.write']})
    assert response.status_code == 200
    assert response.json()['permissions'] == ['knowledge.read', 'knowledge.write']
    db.refresh(session); assert session.revoked_at is not None
    event = db.scalars(select(PlatformStaffAudit)).first()
    assert event.details['before']['role'] == 'content'
    assert event.details['after']['role'] == 'custom'
    assert client.patch('/api/platform/team/1', json={'role': 'viewer', 'is_active': False}).status_code == 409
    assert db.scalar(select(PlatformMembership).where(PlatformMembership.user_id == 1)).is_active
    response = client.patch('/api/platform/team/2', json={'role': 'content', 'is_active': False})
    assert response.status_code == 200
    current.id = 2
    assert client.get('/api/platform/access').status_code == 403


def test_no_custom_wildcard_unknown_role_or_secret_in_validation(environment):
    client, db, current = environment
    for body in ({'role':'custom','permissions':['*']}, {'role':'custom','permissions':['team.manage']},
                 {'role':'custom','permissions':[]}, {'role':'invented'}):
        assert client.patch('/api/platform/team/2', json=body).status_code == 422
    response = client.post('/api/platform/team', json={'full_name':'Test user', 'email':'bad', 'password':'never-return-this-password', 'role':'content'})
    assert response.status_code == 422 and 'never-return' not in response.text
