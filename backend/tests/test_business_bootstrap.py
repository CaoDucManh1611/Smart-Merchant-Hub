import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.business import Business
from app.database.bootstrap import ensure_default_business, ensure_default_plans
from app.models.business import ServicePlan


class DefaultBusinessBootstrapTests(unittest.TestCase):
    def test_default_business_is_created_once_and_reused(self):
        engine = create_engine("sqlite://")
        Business.__table__.create(engine)

        with Session(engine) as session:
            first = ensure_default_business(session)
            second = ensure_default_business(session)

            businesses = session.scalars(select(Business)).all()

        self.assertEqual(first.id, second.id)
        self.assertEqual(1, len(businesses))
        self.assertEqual("default-business", first.slug)
        self.assertEqual("Default Business", first.name)

    def test_default_plans_are_seeded_idempotently(self):
        engine = create_engine("sqlite://")
        ServicePlan.__table__.create(engine)

        with Session(engine) as session:
            first = ensure_default_plans(session)
            session.commit()
            second = ensure_default_plans(session)
            session.commit()
            plans = session.scalars(select(ServicePlan).order_by(ServicePlan.code)).all()

        self.assertEqual(["demo", "starter", "growth", "pro"], [plan.code for plan in first])
        self.assertEqual([plan.id for plan in first], [plan.id for plan in second])
        self.assertEqual(4, len(plans))
        self.assertTrue(all(plan.status == "active" for plan in plans))
        self.assertEqual({"demo": 0, "starter": 1, "growth": 2, "pro": 4}, {plan.code: plan.max_channels for plan in plans})


if __name__ == "__main__":
    unittest.main()
