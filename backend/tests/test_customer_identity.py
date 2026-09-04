import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.customer import Customer
from app.models.customer_identity import CustomerIdentity
from app.services.customer_identity import resolve_customer


class CustomerIdentityResolutionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Business.metadata.create_all(self.engine)

    def test_same_platform_identity_is_reused(self):
        with Session(self.engine) as db:
            business = Business(name="Shop", slug="shop")
            db.add(business)
            db.commit()

            first = resolve_customer(
                db,
                business_id=business.id,
                channel="facebook",
                external_user_id="fb-1",
                external_account_id="page-1",
                name="Nguyen A",
            )
            second = resolve_customer(
                db,
                business_id=business.id,
                channel="facebook",
                external_user_id="fb-1",
                external_account_id="page-1",
            )

            self.assertEqual(first.id, second.id)
            self.assertEqual(1, len(db.scalars(select(Customer)).all()))
            self.assertEqual(1, len(db.scalars(select(CustomerIdentity)).all()))

    def test_verified_phone_links_a_new_channel_to_existing_customer(self):
        with Session(self.engine) as db:
            business = Business(name="Shop", slug="shop")
            db.add(business)
            db.commit()

            first = resolve_customer(
                db,
                business_id=business.id,
                channel="facebook",
                external_user_id="fb-1",
                external_account_id="page-1",
                phone="+84901234567",
            )
            second = resolve_customer(
                db,
                business_id=business.id,
                channel="telegram",
                external_user_id="tg-1",
                external_account_id="bot-1",
                phone="+84901234567",
            )

            self.assertEqual(first.id, second.id)
            self.assertEqual(2, len(db.scalars(select(CustomerIdentity)).all()))

    def test_same_external_id_in_another_business_is_isolated(self):
        with Session(self.engine) as db:
            first_business = Business(name="One", slug="one")
            second_business = Business(name="Two", slug="two")
            db.add_all([first_business, second_business])
            db.commit()

            first = resolve_customer(db, first_business.id, "facebook", "same", "page-1")
            second = resolve_customer(db, second_business.id, "facebook", "same", "page-1")

            self.assertNotEqual(first.id, second.id)


if __name__ == "__main__":
    unittest.main()
