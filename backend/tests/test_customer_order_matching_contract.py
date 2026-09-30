"""Customer order cancellation should resolve and display concrete line items."""

from app.services.customer_order_service import _action_order_candidates, _format_action_choices


def _orders():
    return [
        {
            "order_number": "ORD-1",
            "status_label": "Đang xử lý",
            "total_amount": 300000,
            "channel": "telegram",
            "items": [
                {"name": "Serum Vitamin C", "sku": "SERUM-01", "quantity": 1, "unit_price": 180000, "line_total": 180000},
                {"name": "Kem chống nắng", "sku": "SUN-01", "quantity": 1, "unit_price": 120000, "line_total": 120000},
            ],
        },
        {
            "order_number": "ORD-2",
            "status_label": "Đã giao",
            "total_amount": 180000,
            "channel": "zalo",
            "items": [{"name": "Sữa rửa mặt", "sku": "CLEAN-01", "quantity": 1, "unit_price": 180000, "line_total": 180000}],
        },
    ]


def test_short_product_name_selects_the_order_line():
    candidates = _action_order_candidates(_orders(), "Tôi muốn hủy đơn serum")
    assert [item["order_number"] for item in candidates] == ["ORD-1"]


def test_ambiguous_reply_focuses_on_matching_line_not_full_catalog():
    reply = _format_action_choices(_orders(), action="cancel", query_text="hủy đơn kem chống nắng")
    assert "Kem chống nắng" in reply
    assert "Serum Vitamin C" not in reply
