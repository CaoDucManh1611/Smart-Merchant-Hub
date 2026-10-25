from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from fastapi import HTTPException
from app.api.documents import replace_document
from app.api.local_connectors import _coalesce_meta_ui_outbound_echo
from app.services.auto_reply_service import format_product_catalog_reply, _format_product_detail_reply


def product(kind="retail", price=200000, stock=1):
    return SimpleNamespace(id=1, name="Offering A", sku="SKU-A", price=price,
        stock_quantity=stock, reserved_quantity=0, description="Verified description",
        metadata_={"offering_type": kind, "billing_unit": "lần"})


@pytest.mark.parametrize("kind", ["retail", "service", "rental"])
def test_current_catalog_reloads_price_after_old_answer(kind):
    item = product(kind)
    old = format_product_catalog_reply([item])
    item.price = 250000
    current = format_product_catalog_reply([item])
    assert "200.000" in old
    assert "250.000" in current and "200.000" not in current


def test_service_does_not_claim_zero_stock_means_no_appointments():
    reply = _format_product_detail_reply(product("service", stock=0))
    assert "thời gian bạn chọn" in reply
    assert "hết hàng" not in reply


def replacement_db(rows):
    db = Mock()
    db.query.return_value.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = rows
    return db


def test_replacement_only_switches_after_new_document_is_ready():
    old, new = SimpleNamespace(id=1,status="ready"), SimpleNamespace(id=2,status="processing")
    db = replacement_db([old,new])
    with pytest.raises(HTTPException):
        replace_document(1,2,db,SimpleNamespace(business_id=7))
    assert old.status == "ready"
    db.commit.assert_not_called()
    new.status = "ready"
    with patch("app.api.documents._has_active_ingestion",return_value=False):
        replace_document(1,2,db,SimpleNamespace(business_id=7))
    assert old.status == "superseded" and new.status == "ready"
    db.commit.assert_called_once()


def test_replacement_rejects_missing_or_other_shop_document():
    db = replacement_db([SimpleNamespace(id=1,status="ready")])
    with pytest.raises(HTTPException) as error:
        replace_document(1,2,db,SimpleNamespace(business_id=7))
    assert error.value.status_code == 404
    db.commit.assert_not_called()


def test_meta_history_confirms_uncertain_delivery_without_resending():
    db = Mock()
    imported = SimpleNamespace(id=20,raw_payload={"history_import":True})
    existing = SimpleNamespace(id=10,conversation_id=3,external_message_id=None,
        direction="outbound",content="Reply",media_type=None,media_url=None,
        received_at=None,status="delivery_unknown",raw_payload={},sender_type="bot")
    db.get.return_value = imported
    db.scalars.return_value.all.return_value = [existing]
    result = _coalesce_meta_ui_outbound_echo(db,"facebook",
        {"direction":"outbound","content":"Reply","message_id":"provider-1"},
        {"_created":True,"message_id":20,"conversation_id":3})
    assert result["message_id"] == 10 and not result["_created"]
    assert existing.status == "sent"
    db.delete.assert_called_once_with(imported)
    sql = str(db.scalars.call_args.args[0].compile(compile_kwargs={"literal_binds":True}))
    assert "delivery_unknown" in sql
    assert "messages.id != 20" in sql


def test_meta_qr_caption_echo_matches_without_url_or_leading_emoji():
    db=Mock()
    db.get.return_value=SimpleNamespace(id=20,raw_payload={"history_import":True})
    original=SimpleNamespace(id=10,conversation_id=3,external_message_id=None,direction="outbound",
        content="🏦 Thông tin chuyển khoản đơn TEST-1\nMã QR: https://img.vietqr.io/image/970403-1234567890-compact2.png?amount=1000\nChờ đối soát.",
        media_type="image",media_url="qr",received_at=None,status="delivery_unknown",raw_payload={},sender_type="bot")
    db.scalars.return_value.all.return_value=[original]
    result=_coalesce_meta_ui_outbound_echo(db,"facebook",
        {"direction":"outbound","content":"Thông tin chuyển khoản đơn TEST-1 Chờ đối soát.","message_id":"provider-caption"},
        {"_created":True,"message_id":20,"conversation_id":3})
    assert result["message_id"]==10
    assert original.status=="sent"
