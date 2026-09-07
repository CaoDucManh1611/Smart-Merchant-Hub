import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Business
from app.services.job_service import dispatch_due_jobs, enqueue_job


class CrmJobsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Jobs", slug="jobs")
            db.add(business)
            db.commit()
            cls.business_id = business.id

    def test_enqueue_is_idempotent_and_dispatch_records_success(self):
        with Session(self.engine) as db:
            first = enqueue_job(db, business_id=self.business_id, kind="test.success", payload={"value": 7}, idempotency_key="same-key")
            second = enqueue_job(db, business_id=self.business_id, kind="test.success", payload={"value": 99}, idempotency_key="same-key")
            self.assertEqual(first.id, second.id)
            db.commit()
            processed = dispatch_due_jobs(db, business_id=self.business_id, handlers={"test.success": lambda payload: payload["value"]})
            self.assertEqual(1, processed)
            db.refresh(first)
            self.assertEqual("succeeded", first.status)
            self.assertEqual(1, first.attempts)

    def test_failed_job_is_retried_with_bounded_attempts(self):
        with Session(self.engine) as db:
            job = enqueue_job(db, business_id=self.business_id, kind="test.fail", payload={}, idempotency_key="fail-key")
            db.commit()
            processed = dispatch_due_jobs(db, business_id=self.business_id, handlers={"test.fail": lambda payload: (_ for _ in ()).throw(RuntimeError("boom"))})
            self.assertEqual(1, processed)
            db.refresh(job)
            self.assertEqual("pending", job.status)
            self.assertEqual(1, job.attempts)
            self.assertIsNotNone(job.last_error)
            self.assertIsNotNone(job.run_at)


if __name__ == "__main__":
    unittest.main()
