import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Customer


class CustomerImportApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            first = Business(name="CSV fixture", slug="csv-fixture")
            second = Business(name="Other CSV fixture", slug="other-csv-fixture")
            db.add_all((first, second))
            db.commit()
            cls.business_id, cls.other_business_id = first.id, second.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def _post_csv(self, path: str, text: str, business_id: int):
        return self.client.post(
            f"/api/customers{path}",
            headers={"X-Business-Id": str(business_id)},
            files={"file": ("customers.csv", text.encode("utf-8"), "text/csv")},
        )

    def test_preview_import_repeat_and_tenant_scope(self):
        payload = "name,email,phone\nMai,mai@example.com,\nAn,,0901234567\n"
        preview = self._post_csv("/import/preview", payload, self.business_id)
        self.assertEqual(200, preview.status_code, preview.text)
        self.assertEqual(["create", "create"], [item["action"] for item in preview.json()["rows"]])
        with Session(self.engine) as db:
            self.assertEqual(0, db.query(Customer).filter_by(business_id=self.business_id).count())

        first = self._post_csv("/import", payload, self.business_id)
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual(2, first.json()["created"])
        repeated = self._post_csv("/import", payload, self.business_id)
        self.assertEqual(200, repeated.status_code, repeated.text)
        self.assertEqual({"created": 0, "skipped": 2, "total": 2}, repeated.json())

        other_preview = self._post_csv("/import/preview", payload, self.other_business_id)
        self.assertEqual(["create", "create"], [item["action"] for item in other_preview.json()["rows"]])
        exported = self.client.get(
            "/api/customers/export.csv",
            headers={"X-Business-Id": str(self.business_id)},
        )
        self.assertEqual(200, exported.status_code, exported.text)
        self.assertIn("mai@example.com", exported.text)
        with Session(self.engine) as db:
            self.assertEqual(0, db.query(Customer).filter_by(business_id=self.other_business_id).count())

    def test_invalid_row_aborts_entire_import(self):
        payload = "name,email\nValid,valid@example.com\nBroken,not-an-email\n"
        preview = self._post_csv("/import/preview", payload, self.business_id)
        self.assertEqual(200, preview.status_code, preview.text)
        self.assertIn({"row": 3, "code": "invalid_email"}, preview.json()["errors"])
        imported = self._post_csv("/import", payload, self.business_id)
        self.assertEqual(422, imported.status_code, imported.text)
        with Session(self.engine) as db:
            self.assertIsNone(db.query(Customer).filter_by(email="valid@example.com").first())


if __name__ == "__main__":
    unittest.main()
