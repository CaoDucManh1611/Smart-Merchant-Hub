import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Document, RagRun


class RagOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="RAG Ops", slug="rag-ops")
            db.add(business)
            db.flush()
            document = Document(business_id=business.id, filename="catalog.txt", file_type="txt", status="pending", source_bytes=b"price list")
            db.add(document)
            db.commit()
            cls.business_id = business.id
            cls.document_id = document.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_rag_run_status_is_persisted_and_tenant_scoped(self):
        headers = {"X-Business-Id": str(self.business_id)}
        status = self.client.get(f"/api/documents/{self.document_id}/runs", headers=headers)
        self.assertEqual(200, status.status_code, status.text)
        self.assertEqual([], status.json()["items"])
        dispatch = self.client.post("/api/documents/jobs/dispatch", headers=headers)
        self.assertEqual(200, dispatch.status_code, dispatch.text)

    def test_failed_rag_dispatch_marks_run_failed_with_sanitized_error(self):
        headers = {"X-Business-Id": str(self.business_id)}
        with Session(self.engine) as db:
            document = Document(
                business_id=self.business_id,
                filename="failure.txt",
                file_type="txt",
                status="pending",
                source_bytes=b"failure fixture",
            )
            db.add(document)
            db.commit()
            document_id = document.id
        queued = self.client.post(
            f"/api/documents/{document_id}/reindex",
            headers=headers,
        )
        self.assertEqual(200, queued.status_code, queued.text)

        with patch(
            "app.api.documents.ingest_document",
            side_effect=RuntimeError("embedding provider unavailable; token=secret"),
        ):
            dispatched = self.client.post("/api/documents/jobs/dispatch", headers=headers)

        self.assertEqual(200, dispatched.status_code, dispatched.text)
        with Session(self.engine) as db:
            run = db.query(RagRun).order_by(RagRun.id.desc()).first()
            self.assertEqual("failed", run.status)
            self.assertEqual("complete", run.phase)
            self.assertIn("embedding provider unavailable", run.error_message)
            self.assertNotIn("token=secret", run.error_message)


if __name__ == "__main__":
    unittest.main()
