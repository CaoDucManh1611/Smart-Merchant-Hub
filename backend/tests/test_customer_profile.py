import unittest

from types import SimpleNamespace

from app.services.customer_profile import merge_profile, normalize_phone, select_name


class CustomerProfilePolicyTests(unittest.TestCase):
    def test_name_priority_is_display_name_then_name_then_username(self):
        self.assertEqual(
            "An Nguyen",
            select_name(
                existing=None,
                name="Nguyen An",
                display_name="An Nguyen",
                username="an.shop",
            ),
        )
        self.assertEqual(
            "Nguyen An",
            select_name(existing=None, name="Nguyen An", username="an.shop"),
        )

    def test_profile_values_are_normalized_and_empty_values_do_not_erase_data(self):
        customer = SimpleNamespace(
            name="Khách hàng",
            email="old@example.com",
            phone="090 123 4567",
            avatar_url="https://cdn.example/old.png",
        )
        changes = merge_profile(
            customer,
            name="  Nguyễn   An ",
            email="NEW@Example.COM",
            phone="",
            avatar_url="",
        )
        self.assertEqual("Nguyễn An", customer.name)
        self.assertEqual("new@example.com", customer.email)
        self.assertEqual("0901234567", customer.phone)
        self.assertEqual("https://cdn.example/old.png", customer.avatar_url)
        self.assertEqual({"name", "email", "phone"}, set(changes))

    def test_phone_normalization_keeps_country_prefix_and_digits(self):
        self.assertEqual("+84901234567", normalize_phone("+84 (90) 123-4567"))


if __name__ == "__main__":
    unittest.main()
