import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.customer import Customer


class ExperimentationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Experiment", slug="experiment")
            db.add(business); db.flush()
            customer = Customer(business_id=business.id, channel="telegram", external_user_id="exp-user")
            db.add(customer); db.commit()
            cls.business_id = business.id; cls.customer_id = customer.id
        def override_get_db():
            with Session(cls.engine) as db: yield db
        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls): app.dependency_overrides.clear()

    def headers(self): return {"X-Business-Id": str(self.business_id)}

    def test_rule_suggestion_requires_human_review(self):
        created = self.client.post("/api/experiments/rule-suggestions", headers=self.headers(), json={"title": "Tag VIP", "rationale": "Có nhiều khách hỏi giá", "proposed_action": {"type": "add_tag", "tag": "VIP"}})
        self.assertEqual(201, created.status_code)
        suggestion_id = created.json()["id"]
        self.assertEqual("pending", created.json()["status"])
        reviewed = self.client.post(f"/api/experiments/rule-suggestions/{suggestion_id}/review", headers=self.headers(), json={"status": "accepted"})
        self.assertEqual("accepted", reviewed.json()["status"])

    def test_experiment_assignment_and_outcome(self):
        exp = self.client.post("/api/experiments", headers=self.headers(), json={"name": "Reply A/B", "variants": ["a", "b"], "status": "running"})
        self.assertEqual(201, exp.status_code)
        exp_id = exp.json()["id"]
        assignment = self.client.post(f"/api/experiments/{exp_id}/assign", headers=self.headers(), json={"subject_key": "customer:1"})
        self.assertEqual(200, assignment.status_code)
        outcome = self.client.post(f"/api/experiments/{exp_id}/assignments/{assignment.json()['id']}/outcome", headers=self.headers(), json={"metric": "conversion", "value": "1"})
        self.assertEqual(201, outcome.status_code)
        decision = self.client.post(f"/api/experiments/{exp_id}/bandit/decision", headers=self.headers(), json={"subject_key": "customer:1", "arm": "a", "context": {"channel": "telegram"}})
        self.assertEqual(201, decision.status_code)
        reward = self.client.post(f"/api/experiments/{exp_id}/bandit/{decision.json()['id']}/reward", headers=self.headers(), json={"metric": "reward", "value": "0.8"})
        self.assertEqual("0.8000", reward.json()["reward"])


if __name__ == "__main__": unittest.main()
