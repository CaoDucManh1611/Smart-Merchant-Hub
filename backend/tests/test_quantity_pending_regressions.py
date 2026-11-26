import pytest

from test_business_request import setup
from app.models.customer_collection import CustomerCollectionSession
from app.models.sales import Order, Product
from app.services.customer_collection_flow import advance_customer_collection


@pytest.fixture
def pending_mask(setup):
    db, conversation, mask, *_ = setup
    mask.name = "Mặt nạ đất sét 100g"
    mask.sku = "MASK-100"
    mask.price = 189000
    mask.stock_quantity = 18
    mask.reserved_quantity = 0
    cleanser = Product(
        business_id=1, sku="CLEANSER-REG", name="Sữa rửa mặt dịu nhẹ",
        price=179000, stock_quantity=12, reserved_quantity=0, status="active",
    )
    db.add(cleanser)
    db.commit()
    arguments = dict(
        business_id=1, customer_id=conversation.customer_id,
        conversation_id=conversation.id, source_channel=conversation.channel,
    )
    first = advance_customer_collection(db, text=f"Tôi muốn mua {mask.name}", **arguments)
    assert first.current_field == "quantity"
    session = db.get(CustomerCollectionSession, first.session_id)
    return db, mask, cleanser, session, arguments


def test_pending_quantity_switches_to_explicit_new_product(pending_mask):
    db, mask, cleanser, session, arguments = pending_mask

    reply = advance_customer_collection(
        db, text=f"Không, đổi sang 2 {cleanser.name}", **arguments,
    )

    assert reply.current_field == "order_confirmation"
    assert cleanser.name in reply.prompt and mask.name not in reply.prompt
    assert "358.000" in reply.prompt
    assert [(item["product_id"], item["quantity"])
            for item in session.collected_fields["items"]] == [(cleanser.id, 2)]
    assert not session.collected_fields.get("quantity_pending")
    assert db.query(Order).count() == 0


def test_switch_without_quantity_asks_for_new_product_quantity(pending_mask):
    db, mask, cleanser, session, arguments = pending_mask

    reply = advance_customer_collection(
        db, text=f"Không, tôi muốn mua {cleanser.name}", **arguments,
    )

    assert reply.current_field == "quantity"
    assert cleanser.name in reply.prompt and mask.name not in reply.prompt
    quoted = advance_customer_collection(db, text="2", **arguments)
    assert quoted.current_field == "order_confirmation"
    assert "358.000" in quoted.prompt and mask.name not in quoted.prompt
    assert session.collected_fields["product_id"] == cleanser.id
    assert not session.collected_fields.get("quantity_pending")


def test_out_of_stock_switch_keeps_new_product_for_quantity_correction(pending_mask):
    db, mask, cleanser, session, arguments = pending_mask

    unavailable = advance_customer_collection(
        db, text=f"Không, đổi sang 99 {cleanser.name}", **arguments,
    )

    assert unavailable.current_field == "quantity"
    assert cleanser.name in unavailable.prompt and mask.name not in unavailable.prompt
    quoted = advance_customer_collection(db, text="2", **arguments)
    assert quoted.current_field == "order_confirmation"
    assert cleanser.name in quoted.prompt and mask.name not in quoted.prompt
    assert "358.000" in quoted.prompt
    assert session.collected_fields["product_id"] == cleanser.id
    assert not session.collected_fields.get("quantity_pending")


def test_each_over_stock_cart_item_can_be_corrected_in_sequence(pending_mask):
    db, mask, cleanser, session, arguments = pending_mask
    unavailable = advance_customer_collection(
        db, text=f"Đổi sang 99 {mask.name} và 99 {cleanser.name}", **arguments,
    )
    assert unavailable.status == "stock_unavailable"

    first = advance_customer_collection(db, text="2", **arguments)
    assert first.current_field == "quantity"
    assert cleanser.name in first.prompt
    quoted = advance_customer_collection(db, text="3", **arguments)

    assert quoted.current_field == "order_confirmation"
    assert "915.000" in quoted.prompt
    assert {item["product_id"]: item["quantity"]
            for item in session.collected_fields["items"]} == {mask.id: 2, cleanser.id: 3}
    assert not session.collected_fields.get("quantity_pending")
    assert db.query(Order).count() == 0


def test_quantity_on_one_product_does_not_confirm_another_product_quantity(pending_mask):
    db, mask, cleanser, session, arguments = pending_mask

    pending = advance_customer_collection(
        db, text=f"Mua 2 {mask.name} và {cleanser.name}", **arguments,
    )

    assert pending.current_field == "quantity"
    assert cleanser.name in pending.prompt
    quoted = advance_customer_collection(db, text="3", **arguments)
    assert quoted.current_field == "order_confirmation"
    assert "915.000" in quoted.prompt
    assert {item["product_id"]: item["quantity"]
            for item in session.collected_fields["items"]} == {mask.id: 2, cleanser.id: 3}
    assert not session.collected_fields.get("quantity_pending")
    assert db.query(Order).count() == 0


def test_adding_product_keeps_original_quantity_unresolved(pending_mask):
    db, mask, cleanser, session, arguments = pending_mask

    reply = advance_customer_collection(
        db, text=f"Mua thêm 2 {cleanser.name}", **arguments,
    )

    assert reply.current_field == "quantity"
    assert mask.name in reply.prompt and "bao nhiêu" in reply.prompt
    assert {item["product_id"] for item in session.collected_fields["items"]} == {mask.id, cleanser.id}
    quoted = advance_customer_collection(db, text="3", **arguments)
    assert quoted.current_field == "order_confirmation"
    assert "925.000" in quoted.prompt
    assert {item["product_id"]: item["quantity"]
            for item in session.collected_fields["items"]} == {mask.id: 3, cleanser.id: 2}
    assert not session.collected_fields.get("quantity_pending")
    assert db.query(Order).count() == 0


def test_adding_product_without_quantity_collects_both_quantities(pending_mask):
    db, mask, cleanser, session, arguments = pending_mask

    added = advance_customer_collection(db, text=f"Mua thêm {cleanser.name}", **arguments)
    assert added.current_field == "quantity"
    assert mask.name in added.prompt
    second = advance_customer_collection(db, text="2", **arguments)
    assert second.current_field == "quantity"
    assert cleanser.name in second.prompt
    quoted = advance_customer_collection(db, text="1", **arguments)
    assert quoted.current_field == "order_confirmation"
    assert "557.000" in quoted.prompt
    assert {item["product_id"]: item["quantity"]
            for item in session.collected_fields["items"]} == {mask.id: 2, cleanser.id: 1}


def test_first_explicit_quantity_replaces_unconfirmed_placeholder(pending_mask):
    db, mask, _, session, arguments = pending_mask

    reply = advance_customer_collection(db, text=f"Mua thêm 2 {mask.name}", **arguments)

    assert reply.current_field == "order_confirmation"
    assert session.collected_fields["quantity"] == 2
    assert "378.000" in reply.prompt
    assert not session.collected_fields.get("quantity_pending")


def test_legacy_pending_quantity_session_still_collects_quantity(pending_mask):
    db, _, _, session, arguments = pending_mask
    fields = dict(session.collected_fields)
    fields.pop("quantity_pending_product_ids")
    session.collected_fields = fields
    db.commit()

    reply = advance_customer_collection(db, text="2", **arguments)

    assert reply.current_field == "order_confirmation"
    assert "378.000" in reply.prompt
    assert not session.collected_fields.get("quantity_pending")


@pytest.mark.parametrize("text", ["ok đặt đi", "mình chưa biết"])
def test_missing_quantity_never_accepts_confirmation_as_one_item(pending_mask, text):
    db, mask, _, session, arguments = pending_mask

    reply = advance_customer_collection(db, text=text, **arguments)

    assert reply.current_field == "quantity"
    assert "bao nhiêu" in reply.prompt
    assert session.collected_fields["quantity_pending"]
    assert db.query(Order).count() == 0


def test_quantity_uses_refreshed_available_stock(pending_mask):
    db, mask, _, session, arguments = pending_mask
    mask.stock_quantity = 3
    mask.reserved_quantity = 2
    db.commit()

    unavailable = advance_customer_collection(db, text="2", **arguments)

    assert unavailable.status == "stock_unavailable"
    assert unavailable.current_field == "quantity"
    assert session.collected_fields["quantity_pending"]
    mask.reserved_quantity = 1
    db.commit()
    quoted = advance_customer_collection(db, text="2", **arguments)
    assert quoted.current_field == "order_confirmation"
    assert "378.000" in quoted.prompt
    assert session.collected_fields["quantity"] == 2
    assert not session.collected_fields.get("quantity_pending")
    assert db.query(Order).count() == 0
