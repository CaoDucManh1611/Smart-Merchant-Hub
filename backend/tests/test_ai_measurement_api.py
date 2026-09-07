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


class AiMeasurementApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="AI Measurement", slug="ai-measurement")
            db.add(business); db.flush()
            customer = Customer(business_id=business.id, channel="telegram", external_user_id="ai-user")
            db.add(customer); db.commit()
            cls.business_id = business.id
            cls.customer_id = customer.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db
        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def headers(self):
        return {"X-Business-Id": str(self.business_id)}

    def test_rule_evidence_convert_and_rollback(self):
        created = self.client.post("/api/experiments/rule-suggestions/generate", headers=self.headers(), json={"channel": "telegram", "sample_size": 3, "source_event_ids": ["evt-1"], "evidence": {"keyword": "giá"}})
        self.assertEqual(201, created.status_code, created.text)
        suggestion_id = created.json()["id"]
        self.assertEqual(["evt-1"], created.json()["source_event_ids"])
        reviewed = self.client.post(f"/api/experiments/rule-suggestions/{suggestion_id}/review", headers=self.headers(), json={"status": "accepted", "reviewer_note": "ok"})
        self.assertEqual(200, reviewed.status_code, reviewed.text)
        converted = self.client.post(f"/api/experiments/rule-suggestions/{suggestion_id}/convert", headers=self.headers())
        self.assertEqual(200, converted.status_code, converted.text)
        self.assertEqual("draft", converted.json()["workflow_status"])
        rolled = self.client.post(f"/api/experiments/rule-suggestions/{suggestion_id}/rollback", headers=self.headers())
        self.assertEqual("rolled_back", rolled.json()["status"])

    def test_model_training_is_versioned_and_inference_is_deterministic(self):
        for value, label in [(1, 0), (2, 1), (3, 1), (4, 1)]:
            self.client.post("/api/experiments/features/snapshots", headers=self.headers(), json={"customer_id": self.customer_id, "feature_version": "v1", "features": {"score": value}, "label": {"converted": label}})
        model = self.client.post("/api/experiments/models", headers=self.headers(), json={"name": "conversion", "version": "1", "feature_version": "v1", "target": "converted"})
        self.assertEqual(201, model.status_code, model.text)
        trained = self.client.post(f"/api/experiments/models/{model.json()['id']}/train", headers=self.headers(), json={"holdout_ratio": 0.25})
        self.assertEqual(201, trained.status_code, trained.text)
        inferred = self.client.post(f"/api/experiments/models/{model.json()['id']}/infer", headers=self.headers(), json={"features": {"score": 4}})
        self.assertEqual(200, inferred.status_code, inferred.text)
        self.assertEqual("1", inferred.json()["model_version"])
        self.assertIn("confidence", inferred.json())
        self.assertIn("mae", inferred.json()["metrics"])
        self.assertLessEqual(inferred.json()["confidence"], 1)

    def test_exposure_report_stop_and_bandit_policy(self):
        exp = self.client.post("/api/experiments", headers=self.headers(), json={"name": "Reply", "variants": ["a", "b"], "status": "running", "min_sample_size": 1})
        self.assertEqual(201, exp.status_code, exp.text)
        experiment_id = exp.json()["id"]
        exposure = self.client.post(f"/api/experiments/{experiment_id}/exposures", headers=self.headers(), json={"subject_key": "s1", "variant": "a", "idempotency_key": "x1"})
        self.assertEqual(201, exposure.status_code, exposure.text)
        self.assertEqual(exposure.json()["id"], self.client.post(f"/api/experiments/{experiment_id}/exposures", headers=self.headers(), json={"subject_key": "s1", "variant": "a", "idempotency_key": "x1"}).json()["id"])
        assignment = self.client.post(f"/api/experiments/{experiment_id}/assign", headers=self.headers(), json={"subject_key": "s2", "variant": "b"})
        self.assertEqual(200, assignment.status_code, assignment.text)
        outcome = self.client.post(f"/api/experiments/{experiment_id}/assignments/{assignment.json()['id']}/outcome", headers=self.headers(), json={"metric": "conversion", "value": "1", "idempotency_key": "out-1"})
        self.assertEqual(201, outcome.status_code, outcome.text)
        report = self.client.get(f"/api/experiments/{experiment_id}/report", headers=self.headers())
        self.assertEqual(200, report.status_code, report.text)
        self.assertTrue(report.json()["stopped"])
        policy = self.client.post(f"/api/experiments/{experiment_id}/bandit/policies", headers=self.headers(), json={"version": "p1", "epsilon": "0"})
        self.assertEqual(201, policy.status_code, policy.text)
        # A completed experiment cannot be selected; this is an explicit safety boundary.
        blocked = self.client.post(f"/api/experiments/{experiment_id}/bandit/select", headers=self.headers(), json={"subject_key": "s3", "context": {"channel": "telegram"}})
        self.assertEqual(409, blocked.status_code)


if __name__ == "__main__":
    unittest.main()
