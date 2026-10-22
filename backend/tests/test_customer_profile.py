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
        self.assertEqual(
            "Tên hiển thị đáng tin cậy",
            select_name(
                existing="Tên hiển thị đáng tin cậy",
                existing_priority=3,
                name="Tên từ nguồn thấp hơn",
            ),
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

    def test_meta_ui_labels_and_icons_do_not_overwrite_real_customer_profile(self):
        for label in ("Chia sẻ dữ liệu", "Trang cá nhân trên Facebook", "Share data", "Facebook profile"):
            customer = SimpleNamespace(name="Phú Lê", email=None, phone=None, avatar_url="https://scontent.fbcdn.net/photo.jpg")
            changes = merge_profile(customer, display_name=label, avatar_url="https://static.xx.fbcdn.net/rsrc.php/icon.webp")
            self.assertEqual({}, changes)
            self.assertEqual("Phú Lê", customer.name)
            self.assertEqual("https://scontent.fbcdn.net/photo.jpg", customer.avatar_url)


if __name__ == "__main__":
    unittest.main()
