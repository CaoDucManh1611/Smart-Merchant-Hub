import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.customer import Customer
from app.tenancy.scoped_queries import get_customer_for_tenant


class TenantScopedQueryTests(unittest.TestCase):
    def test_cross_tenant_customer_is_not_returned(self):
        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
        with Session(engine) as db:
            one = Business(name="One", slug="one")
            two = Business(name="Two", slug="two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(
                business_id=one.id,
                channel="facebook",
                external_user_id="u1",
            )
            db.add(customer)
            db.commit()

            self.assertIsNone(get_customer_for_tenant(db, customer.id, two.id))
            self.assertEqual(customer.id, get_customer_for_tenant(db, customer.id, one.id).id)


if __name__ == "__main__":
    unittest.main()
