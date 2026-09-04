from unittest.mock import Mock, patch

from app.services.auto_reply_service import _send_channel_reply


def test_auto_reply_dispatches_telegram_through_tenant_channel():
    db = Mock()
    with patch(
        "app.services.auto_reply_service.send_telegram_message",
        return_value={"ok": True, "result": {"message_id": 42}},
    ) as send:
        response = _send_channel_reply(
            db=db,
            conversation_id=7,
            channel="telegram",
            recipient_id="12345",
            text="Serum Vitamin C giá 420.000 đồng.",
            business_id=1,
        )

    assert response["ok"] is True
    send.assert_called_once_with(
        db=db,
        business_id=1,
        conversation_id=7,
        recipient_id="12345",
        text="Serum Vitamin C giá 420.000 đồng.",
    )


def test_auto_reply_dispatches_zalo_through_tenant_channel():
    db = Mock()
    with patch(
        "app.services.auto_reply_service.send_zalo_message",
        return_value={"ok": True, "result": {"message_id": "z-out-1"}},
    ) as send:
        response = _send_channel_reply(
            db=db,
            conversation_id=8,
            channel="zalo",
            recipient_id="z-user-1",
            text="Serum Vitamin C giá 420.000 đồng.",
            business_id=1,
        )

    assert response["ok"] is True
    send.assert_called_once_with(
        db=db,
        business_id=1,
        conversation_id=8,
        recipient_id="z-user-1",
        text="Serum Vitamin C giá 420.000 đồng.",
    )
