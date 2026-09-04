import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.business import Business
from app.database.bootstrap import ensure_default_business


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


if __name__ == "__main__":
    unittest.main()
