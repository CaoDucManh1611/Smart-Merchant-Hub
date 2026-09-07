import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Business, Conversation, CrmJob, Customer, Notification, Ticket, Workflow, WorkflowRun
from app.services.crm_job_worker import dispatch_all_crm_jobs
from app.services.job_service import enqueue_job


class CrmJobWorkerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            primary = Business(name="Worker primary", slug="worker-primary")
            other = Business(name="Worker other", slug="worker-other")
            db.add_all([primary, other])
            db.flush()
            customer = Customer(
                business_id=primary.id,
                channel="telegram",
                external_user_id="worker-customer",
            )
            db.add(customer)
            db.flush()
            conversation = Conversation(
                business_id=primary.id,
                customer_id=customer.id,
                channel="telegram",
            )
            db.add(conversation)
            db.flush()
            db.commit()
            self.primary_id = primary.id
            self.customer_id = customer.id
            self.conversation_id = conversation.id

    def tearDown(self):
        self.engine.dispose()

    def test_worker_dispatches_sla_and_workflow_jobs_without_http_request(self):
        with Session(self.engine) as db:
            ticket = Ticket(
                business_id=self.primary_id,
                customer_id=self.customer_id,
                conversation_id=self.conversation_id,
                title="SLA đã quá hạn",
                status="open",
                priority="urgent",
            sla_due_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1),
            )
            workflow = Workflow(
                business_id=self.primary_id,
                name="Delayed ticket",
                event_type="message.created",
                conditions={},
                actions=[{"type": "create_ticket", "title": "Ticket từ workflow"}],
                enabled=True,
            )
            db.add_all([ticket, workflow])
            db.flush()
            enqueue_job(
                db,
                business_id=self.primary_id,
                kind="ticket.sla_check",
                payload={"ticket_id": ticket.id},
                idempotency_key=f"ticket:{ticket.id}:sla:{ticket.sla_due_at.isoformat()}",
                run_at=ticket.sla_due_at,
            )
            enqueue_job(
                db,
                business_id=self.primary_id,
                kind="workflow.run",
                payload={
                    "workflow_id": workflow.id,
                    "event_id": "worker-message-1",
                    "event_type": "message.created",
                    "event_payload": {
                        "customer_id": self.customer_id,
                        "conversation_id": self.conversation_id,
                    },
                },
                idempotency_key=f"workflow:{workflow.id}:worker-message-1",
            )
            db.commit()
            processed = dispatch_all_crm_jobs(db)
            self.assertEqual(2, processed)
            notifications = db.scalars(
                select(Notification).where(
                    Notification.business_id == self.primary_id,
                    Notification.kind == "sla",
                )
            ).all()
            self.assertEqual(1, len(notifications))
            workflow_run = db.scalar(select(WorkflowRun).where(WorkflowRun.event_id == "worker-message-1"))
            self.assertIsNotNone(workflow_run)
            self.assertEqual("completed", workflow_run.status)
            created_ticket = db.scalar(
                select(Ticket).where(
                    Ticket.business_id == self.primary_id,
                    Ticket.title == "Ticket từ workflow",
                )
            )
            self.assertIsNotNone(created_ticket)
            sla_jobs = db.scalars(
                select(CrmJob).where(
                    CrmJob.business_id == self.primary_id,
                    CrmJob.kind == "ticket.sla_check",
                )
            ).all()
            follow_up_job = next(
                (job for job in sla_jobs if (job.payload or {}).get("ticket_id") == created_ticket.id),
                None,
            )
            self.assertIsNotNone(follow_up_job)
            self.assertEqual("pending", follow_up_job.status)

    def test_failed_workflow_job_stays_pending_for_retry(self):
        with Session(self.engine) as db:
            workflow = Workflow(
                business_id=self.primary_id,
                name="Workflow thiếu customer",
                event_type="message.created",
                conditions={},
                actions=[{"type": "create_ticket", "title": "Không thể tạo"}],
                enabled=True,
            )
            db.add(workflow)
            db.flush()
            job = enqueue_job(
                db,
                business_id=self.primary_id,
                kind="workflow.run",
                payload={
                    "workflow_id": workflow.id,
                    "event_id": "worker-message-invalid",
                    "event_type": "message.created",
                    "event_payload": {},
                },
                idempotency_key=f"workflow:{workflow.id}:worker-message-invalid",
            )
            db.commit()
            job_id = job.id
            workflow_id = workflow.id

        with Session(self.engine) as db:
            self.assertEqual(1, dispatch_all_crm_jobs(db))
            job = db.get(CrmJob, job_id)
            run = db.scalar(
                select(WorkflowRun).where(
                    WorkflowRun.workflow_id == workflow_id,
                    WorkflowRun.event_id == "worker-message-invalid",
                )
            )
            self.assertEqual("pending", job.status)
            self.assertEqual(1, job.attempts)
            self.assertIsNotNone(job.last_error)
            self.assertIsNotNone(run)
            self.assertEqual("failed", run.status)


if __name__ == "__main__":
    unittest.main()
