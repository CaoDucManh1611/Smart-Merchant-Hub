"""Isolated HTTP contracts: no live database, auth or provider calls."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.auth.platform import require_platform_admin
from app.database.platform_session import get_platform_db
from app.db.dependencies import get_db
from app.models.platform_control import PlatformBusiness, SupportGrant
from app.models.platform_support_request import PlatformSupportRequest, PlatformSupportRequestHistory
from app.api.platform_support_requests import router


class SupportRequestTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        event.listen(self.engine, 'connect', lambda conn, _: conn.execute('PRAGMA foreign_keys=ON'))
        for table in (PlatformBusiness.__table__, PlatformSupportRequest.__table__, PlatformSupportRequestHistory.__table__):
            table.create(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([PlatformBusiness(id=i, name=f'Shop {i}', slug=f'shop-{i}', status='active') for i in (1, 2)])
        self.db.commit()
        self.user = SimpleNamespace(id=11, business_id=1)
        app = FastAPI()
        app.include_router(router, prefix='/api')
        def session():
            yield self.db
        def admin():
            if self.user.id != 99:
                raise HTTPException(403, 'platform_admin_required')
            return self.user
        app.dependency_overrides.update({get_platform_db: session, get_db: session,
            get_current_user: lambda: self.user, require_platform_admin: admin})
        self.client = TestClient(app)
        self.payload = {'provider': 'facebook', 'description': 'Không thể kết nối trang bán hàng.', 'idempotency_key': 'request-0001'}

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def create(self, **changes):
        return self.client.post('/api/support/requests', json={**self.payload, **changes})

    def test_create_replay_conflict_and_durable_history(self):
        first = self.create()
        self.assertEqual(first.status_code, 201, first.text)
        ticket = first.json()
        self.assertEqual(ticket['business_id'], 1)
        self.assertEqual(ticket['status'], 'open')
        self.assertEqual(len(ticket['history']), 1)
        self.assertEqual(self.create().json()['id'], ticket['id'])
        self.assertEqual(self.create(description='Một lỗi khác.').status_code, 409)
        self.assertEqual(len(self.db.scalars(select(PlatformSupportRequest)).all()), 1)
        self.db.expire_all()
        self.assertEqual(len(self.db.scalars(select(PlatformSupportRequestHistory)).all()), 1)
        self.assertNotIn(SupportGrant.__tablename__, self.engine.dialect.get_table_names(self.db.connection()))

    def test_own_shop_isolation_and_pagination(self):
        first = self.create().json()
        self.user = SimpleNamespace(id=22, business_id=2)
        self.assertEqual(self.client.get('/api/support/requests').json()['total'], 0)
        second = self.create().json()
        self.assertNotEqual(second['id'], first['id'])
        self.assertEqual(self.client.get('/api/support/requests?limit=1&offset=0').json()['items'][0]['business_id'], 2)
        self.assertEqual(self.client.get('/api/support/requests?offset=1').json()['items'], [])
        self.assertEqual(self.client.get('/api/support/requests?limit=101').status_code, 422)
        self.assertEqual(self.client.get('/api/support/requests?status=invalid').status_code, 422)

    def test_validation_prevents_diagnostics_and_secrets(self):
        for changes in ({'provider': 'unknown'}, {'description': ' '}, {'description': 'x' * 2001},
                        {'description': 'access_token=private'}, {'description': 'Authorization: Bearer abc'},
                        {'description': 'https://example.com?code=secret'}, {'description': '{"error": "raw"}'},
                        {'business_id': 2}, {'diagnostics': 'raw'}, {'idempotency_key': 'short'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.create(**changes).status_code, 422)
        result = self.create(description='<b> Kết nối thất bại </b>\u0000').json()
        self.assertEqual(result['description'], 'Kết nối thất bại')

    def test_missing_shop_and_sync_failure(self):
        self.user = SimpleNamespace(id=11, business_id=None)
        self.assertEqual(self.create().status_code, 403)
        self.user = SimpleNamespace(id=11, business_id=3)
        with patch('app.api.platform_support_requests._sync_platform_business', side_effect=HTTPException(404, 'Shop không tồn tại.')):
            self.assertEqual(self.create().status_code, 404)

    def test_sync_uses_authenticated_identity(self):
        self.user = SimpleNamespace(id=11, business_id=3)
        def sync(platform_db, legacy_db, business_id):
            self.assertEqual(business_id, 3)
            platform_db.add(PlatformBusiness(id=3, name='Synced', slug='synced', status='active'))
            platform_db.flush()
        with patch('app.api.platform_support_requests._sync_platform_business', side_effect=sync):
            self.assertEqual(self.create().json()['business_id'], 3)

    def test_admin_auth_assignment_transitions_and_history(self):
        ticket_id = self.create().json()['id']
        path = f'/api/platform/support-requests/{ticket_id}'
        self.assertEqual(self.client.get('/api/platform/support-requests').status_code, 403)
        self.assertEqual(self.client.patch(path, json={'status': 'in_progress'}).status_code, 403)
        self.user = SimpleNamespace(id=99, business_id=None)
        self.assertEqual(self.client.patch(path, json={'assigned_admin_id': 100}).status_code, 403)
        self.assertEqual(self.client.patch(path, json={'status': 'closed'}).status_code, 409)
        self.assertEqual(self.client.patch(path, json={}).status_code, 422)
        self.assertEqual(self.client.patch(path, json={'response': None}).status_code, 422)
        response = self.client.patch(path, json={'status': 'in_progress', 'response': 'Đang kiểm tra.', 'assigned_admin_id': 99})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['assigned_admin_id'], 99)
        self.assertEqual(len(response.json()['history']), 2)
        self.assertEqual(response.json()['history'][-1]['actor_user_id'], 99)
        self.assertEqual(self.client.get('/api/platform/support-requests?status=in_progress').json()['total'], 1)
        self.assertEqual(self.client.patch(path, json={'response': 'token=secret'}).status_code, 422)
        for status in ('resolved', 'in_progress', 'resolved', 'closed'):
            self.assertEqual(self.client.patch(path, json={'status': status}).status_code, 200)
        self.assertEqual(self.client.patch(path, json={'status': 'open'}).status_code, 409)
        self.assertEqual(self.client.patch('/api/platform/support-requests/999', json={'status': 'resolved'}).status_code, 404)

    def test_database_failure_rolls_back_with_safe_error(self):
        from sqlalchemy.exc import SQLAlchemyError
        with patch.object(self.db, 'commit', side_effect=SQLAlchemyError('private infrastructure detail')):
            response = self.create()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private', response.text)
        self.assertEqual(self.client.get('/api/support/requests').json()['total'], 0)

    def test_opaque_credentials_and_embedded_html_are_not_persisted(self):
        for index, description in enumerate(('Kết nối lỗi eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature',
                            '<script>privateDiagnostic()</script> Kết nối lỗi',
                            'Mã lỗi ' + 'A' * 100)):
            with self.subTest(description=description):
                self.assertEqual(self.create(description=description, idempotency_key=f'opaque-{index}').status_code, 422)

    def test_normalization_cannot_reconstruct_credentials(self):
        for index, description in enumerate(('to<b></b>ken=private', 'https<b></b>://example.com?code=private', 'pass\u0000word=private')):
            with self.subTest(description=description):
                self.assertEqual(self.create(description=description, idempotency_key=f'normalize-{index}').status_code, 422)
        ticket_id = self.create().json()['id']
        self.user = SimpleNamespace(id=99, business_id=None)
        self.assertEqual(self.client.patch(f'/api/platform/support-requests/{ticket_id}',
            json={'response': 'pass\u0000word=private'}).status_code, 422)

    def test_database_constraints_and_migration_in_memory(self):
        import importlib.util
        from pathlib import Path
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import inspect
        from sqlalchemy.exc import IntegrityError

        row = self.create().json()
        with self.assertRaises(IntegrityError):
            self.db.execute(PlatformSupportRequest.__table__.insert().values(
                business_id=1, created_by_user_id=11, idempotency_key=self.payload['idempotency_key'],
                request_fingerprint='a' * 64, provider='facebook', description='Duplicate', status='open'))
        self.db.rollback()
        with self.assertRaises(IntegrityError):
            self.db.execute(PlatformSupportRequest.__table__.insert().values(
                business_id=404, created_by_user_id=11, idempotency_key='missing-shop',
                request_fingerprint='a' * 64, provider='facebook', description='Missing', status='open'))
        self.db.rollback()
        with self.assertRaises(IntegrityError):
            self.db.execute(PlatformSupportRequest.__table__.delete().where(PlatformSupportRequest.id == row['id']))
        self.db.rollback()
        path = Path('/app/alembic_platform/versions/20261011_0002_support_requests.py')
        if not path.exists():
            path = Path(__file__).resolve().parents[1] / 'alembic_platform/versions/20261011_0002_support_requests.py'
        spec = importlib.util.spec_from_file_location('support_migration', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine('sqlite://')
        with engine.begin() as connection:
            PlatformBusiness.__table__.create(connection)
            with patch.object(migration, 'op', Operations(MigrationContext.configure(connection))):
                migration.upgrade()
                for model in (PlatformSupportRequest, PlatformSupportRequestHistory):
                    columns = inspect(connection).get_columns(model.__tablename__)
                    self.assertEqual({column['name'] for column in columns}, set(model.__table__.columns.keys()))
                migration.downgrade()
                self.assertEqual(inspect(connection).get_table_names(), ['platform_businesses'])
        engine.dispose()

    def test_auth_failure_and_cross_shop_header_cannot_override_identity(self):
        result = self.client.post('/api/support/requests', headers={'X-Business-Id': '2'}, json=self.payload)
        self.assertEqual(result.json()['business_id'], 1)
        def unauthorized():
            raise HTTPException(401, 'not_authenticated')
        self.client.app.dependency_overrides[get_current_user] = unauthorized
        self.assertEqual(self.create().status_code, 401)
        self.assertEqual(self.client.get('/api/support/requests').status_code, 401)


if __name__ == '__main__':
    unittest.main()
