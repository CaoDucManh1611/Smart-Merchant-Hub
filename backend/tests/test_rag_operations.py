import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, CrmJob, Document, DocumentChunk, RagRun
from app.services.rag_job_service import dispatch_rag_job


class RagOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="RAG Ops", slug="rag-ops")
            other_business = Business(name="Other RAG Ops", slug="other-rag-ops")
            db.add_all((business, other_business))
            db.flush()
            document = Document(business_id=business.id, filename="catalog.txt", file_type="txt", status="pending", source_bytes=b"price list")
            db.add(document)
            db.commit()
            cls.business_id = business.id
            cls.other_business_id = other_business.id
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

    def test_failed_rag_run_can_be_retried_as_a_new_queued_run(self):
        headers = {"X-Business-Id": str(self.business_id)}
        with Session(self.engine) as db:
            document = Document(
                business_id=self.business_id,
                filename="retry.txt",
                file_type="txt",
                status="failed",
                source_bytes=b"retry fixture",
            )
            db.add(document)
            db.flush()
            failed = RagRun(
                business_id=self.business_id,
                document_id=document.id,
                kind="reindex",
                status="failed",
                phase="complete",
                error_message="provider unavailable",
            )
            db.add(failed)
            db.commit()
            failed_id = failed.id

        retried = self.client.post(f"/api/documents/runs/{failed_id}/retry", headers=headers)
        self.assertEqual(201, retried.status_code, retried.text)
        body = retried.json()
        self.assertNotEqual(failed_id, body["id"])
        self.assertEqual("queued", body["status"])
        self.assertEqual("retry", body["kind"])
        with Session(self.engine) as db:
            original = db.get(RagRun, failed_id)
            self.assertEqual("failed", original.status)

        duplicate = self.client.post(f"/api/documents/runs/{failed_id}/retry", headers=headers)
        self.assertEqual(409, duplicate.status_code, duplicate.text)

    def test_upload_only_persists_source_and_queues_background_work(self):
        headers = {"X-Business-Id": str(self.business_id)}
        with patch("app.api.documents.ingest_document") as ingest:
            response = self.client.post(
                "/api/documents/upload",
                headers=headers,
                files={"file": ("worker-only.txt", b"knowledge content", "text/plain")},
            )

        self.assertEqual(201, response.status_code, response.text)
        ingest.assert_not_called()
        with Session(self.engine) as db:
            document = db.query(Document).filter_by(filename="worker-only.txt").one()
            run = db.query(RagRun).filter_by(document_id=document.id).one()
            job = db.query(CrmJob).filter_by(business_id=self.business_id, kind="rag.ingest").order_by(CrmJob.id.desc()).first()
            self.assertEqual("pending", document.status)
            self.assertEqual("queued", run.status)
            self.assertEqual("pending", job.status)
            self.assertEqual(run.id, job.payload["run_id"])

    def test_duplicate_upload_is_blocked_within_shop_but_allowed_for_other_shop(self):
        payload = b"Unique knowledge content for duplicate check."
        headers = {"X-Business-Id": str(self.business_id)}
        other_headers = {"X-Business-Id": str(self.other_business_id)}
        with patch("app.api.documents.ingest_document"):
            first = self.client.post(
                "/api/documents/upload",
                headers=headers,
                files={"file": ("same.txt", payload, "text/plain")},
            )
            repeated = self.client.post(
                "/api/documents/upload",
                headers=headers,
                files={"file": ("renamed.txt", payload, "text/plain")},
            )
            other_shop = self.client.post(
                "/api/documents/upload",
                headers=other_headers,
                files={"file": ("same.txt", payload, "text/plain")},
            )

        self.assertEqual(201, first.status_code, first.text)
        self.assertEqual(409, repeated.status_code, repeated.text)
        self.assertEqual("duplicate_document", repeated.headers.get("x-error-code"))
        self.assertEqual(201, other_shop.status_code, other_shop.text)

    def test_invalid_document_bytes_are_rejected_before_persistence(self):
        response = self.client.post(
            "/api/documents/upload",
            headers={"X-Business-Id": str(self.business_id)},
            files={"file": ("broken.pdf", b"not a PDF", "application/pdf")},
        )

        self.assertEqual(400, response.status_code, response.text)
        self.assertEqual("invalid_file_content", response.headers.get("x-error-code"))
        with Session(self.engine) as db:
            self.assertIsNone(db.query(Document).filter_by(filename="broken.pdf").first())

    def test_oversized_upload_is_rejected_before_quota_reservation(self):
        from app.api.documents import MAX_DOCUMENT_BYTES

        with patch("app.api.documents.reserve_quota") as reserve:
            response = self.client.post(
                "/api/documents/upload",
                headers={"X-Business-Id": str(self.business_id)},
                files={"file": ("large.txt", b"x" * (MAX_DOCUMENT_BYTES + 1), "text/plain")},
            )

        self.assertEqual(400, response.status_code, response.text)
        self.assertEqual("file_too_large", response.headers.get("x-error-code"))
        reserve.assert_not_called()

    def test_upload_rolls_back_document_when_queue_creation_fails(self):
        headers = {"X-Business-Id": str(self.business_id)}
        with patch("app.api.documents.enqueue_job", side_effect=RuntimeError("queue unavailable")):
            response = self.client.post(
                "/api/documents/upload",
                headers=headers,
                files={"file": ("queue-failure.txt", b"must not persist", "text/plain")},
            )

        self.assertEqual(503, response.status_code, response.text)
        self.assertNotIn("queue unavailable", response.text)
        with Session(self.engine) as db:
            self.assertIsNone(db.query(Document).filter_by(filename="queue-failure.txt").first())

    def test_worker_progress_is_monotonic_and_finishes_at_one_hundred(self):
        with Session(self.engine) as db:
            document = Document(
                business_id=self.business_id,
                filename="progress.txt",
                file_type="txt",
                status="pending",
                source_bytes=b"progress fixture",
            )
            db.add(document)
            db.flush()
            run = RagRun(
                business_id=self.business_id,
                document_id=document.id,
                kind="ingestion",
                status="queued",
            )
            db.add(run)
            db.commit()

            def ingest(document_id, _source, _filename, session, *, business_id, progress_callback):
                progress_callback(60, "embed", 10, 6)
                progress_callback(40, "embed", 10, 4)
                current = session.get(Document, document_id)
                current.status = "ready"
                current.embedding_status = "ready"
                current.chunk_count = 10
                session.commit()

            dispatch_rag_job(
                db,
                {"run_id": run.id, "document_id": document.id},
                self.business_id,
                ingest_fn=ingest,
            )

            db.refresh(run)
            self.assertEqual("completed", run.status)
            self.assertEqual(100, run.progress_percent)
            self.assertEqual(10, run.completed_chunks)

    def test_delete_rejects_active_ingestion_and_preserves_document(self):
        with Session(self.engine) as db:
            document = Document(
                business_id=self.business_id, filename="active-delete.txt",
                file_type="txt", status="pending", source_bytes=b"knowledge",
            )
            db.add(document)
            db.flush()
            db.add(RagRun(
                business_id=self.business_id, document_id=document.id,
                kind="ingestion", status="queued",
            ))
            db.commit()
            document_id = document.id

        response = self.client.delete(
            f"/api/documents/{document_id}",
            headers={"X-Business-Id": str(self.business_id)},
        )
        self.assertEqual(409, response.status_code, response.text)
        with Session(self.engine) as db:
            self.assertIsNotNone(db.get(Document, document_id))

    def test_delete_removes_document_chunks_from_index(self):
        with Session(self.engine) as db:
            document = Document(
                business_id=self.business_id, filename="delete-ready.txt",
                file_type="txt", status="ready", chunk_count=1,
            )
            db.add(document)
            db.flush()
            db.add(DocumentChunk(
                document_id=document.id, chunk_index=0, content="Private shop knowledge",
            ))
            db.commit()
            document_id = document.id

        response = self.client.delete(
            f"/api/documents/{document_id}",
            headers={"X-Business-Id": str(self.business_id)},
        )
        self.assertEqual(204, response.status_code, response.text)
        with Session(self.engine) as db:
            self.assertIsNone(db.get(Document, document_id))
            self.assertEqual(0, db.query(DocumentChunk).filter_by(document_id=document_id).count())


if __name__ == "__main__":
    unittest.main()
