from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.api.zalo_personal import ZaloPersonalIncoming
from app.core.config import settings
from app.models.sales import Product
from app.schemas.sales import ProductCreate
from app.rag.llm_caller import call_llm_with_image
from app.services.auto_reply_service import (
    _match_customer_image_to_product,
    _should_match_image_to_product,
    process_rag_auto_reply,
)
from app.services.inbound_image_service import _image_url_for_message, download_inbound_image_url
from app.services.product_image_match import parse_product_match, product_image_url, rank_product_image_candidates


@pytest.mark.parametrize("channel", ["facebook", "instagram", "telegram", "zalo", "tiktok", "shopee"])
def test_latest_inbound_image_url_is_available_for_each_channel(channel):
    url = f"https://cdn.example/{channel}.jpg"
    source = SimpleNamespace(channel=channel, media_type="image", media_url=url)
    db = Mock()
    db.query.return_value.join.return_value.filter.return_value.first.return_value = source

    assert _image_url_for_message(
        db,
        business_id=12,
        conversation_id=34,
        message_id=56,
    ) == (url, channel)


def test_image_only_turn_context_triggers_catalog_matching():
    assert _should_match_image_to_product(
        "Khách gửi ảnh đính kèm. Hãy xem ảnh khi trả lời; nếu chưa có câu hỏi rõ, hỏi một câu làm rõ."
    )
    assert _should_match_image_to_product("Ảnh này còn hàng không?")
    assert not _should_match_image_to_product("Ảnh hóa đơn này bị mờ")


def test_product_candidates_require_catalog_description_overlap_and_reference_image():
    shirt = Product(
        id=1,
        business_id=7,
        sku="SHIRT-PINK-01",
        name="Áo sơ mi cotton hồng",
        description="Áo sơ mi nữ cotton tay dài",
        status="active",
        metadata_={"image_url": "https://cdn.example/shirt.jpg", "attributes": {"color": "hồng"}},
    )
    kettle = Product(
        id=2,
        business_id=7,
        sku="KETTLE-01",
        name="Ấm siêu tốc",
        description="Ấm điện gia dụng inox",
        status="active",
        metadata_={"image_url": "https://cdn.example/kettle.jpg"},
    )

    ranked = rank_product_image_candidates([shirt, kettle], "Áo sơ mi cotton màu hồng", limit=5)

    assert [candidate.product.sku for candidate in ranked] == ["SHIRT-PINK-01"]
    assert product_image_url(ranked[0].product) == "https://cdn.example/shirt.jpg"
    assert parse_product_match('{"product_sku":"SHIRT-PINK-01","confidence":0.93}', {"SHIRT-PINK-01"}) == (
        "SHIRT-PINK-01",
        0.93,
    )
    assert parse_product_match('{"product_sku":"KETTLE-01","confidence":0.99}', {"SHIRT-PINK-01"}) == (
        None,
        0.0,
    )


@pytest.mark.parametrize("confidence,expected_match", [(0.94, True), (0.79, False)])
def test_matcher_describes_then_verifies_against_shop_reference_photos(confidence, expected_match):
    shirt = Product(
        id=1,
        business_id=7,
        sku="SHIRT-PINK-01",
        name="Áo sơ mi cotton hồng",
        description="Áo sơ mi nữ cotton tay dài",
        status="active",
        metadata_={"image_url": "https://cdn.example/shirt.jpg"},
    )
    db = Mock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [shirt]

    with patch(
        "app.services.auto_reply_service.call_llm_with_image",
        side_effect=[
            "Áo sơ mi cotton màu hồng, tay dài",
            f'{{"product_sku":"SHIRT-PINK-01","confidence":{confidence}}}',
        ],
    ) as vision, patch(
        "app.services.auto_reply_service.download_inbound_image_url",
        return_value=(b"shop-photo", "image/jpeg"),
    ):
        match, candidates, description = _match_customer_image_to_product(
            db,
            business_id=7,
            image_bytes=b"customer-photo",
            image_mime_type="image/jpeg",
        )

    assert (match is shirt) is expected_match
    assert [candidate.sku for candidate in candidates] == ["SHIRT-PINK-01"]
    assert description == "Áo sơ mi cotton màu hồng, tay dài"
    assert vision.call_count == 2
    assert vision.call_args.kwargs["reference_images"] == [
        ("Ảnh sản phẩm tham chiếu — SKU SHIRT-PINK-01", b"shop-photo", "image/jpeg")
    ]


def test_vision_caller_sends_both_customer_and_reference_images(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    with patch("app.rag.llm_caller.call_groq_vision", return_value="ok") as provider:
        answer = call_llm_with_image(
            [{"role": "user", "content": "Tìm sản phẩm giống ảnh này"}],
            b"customer-photo",
            "image/jpeg",
            reference_images=[("SKU X", b"catalog-photo", "image/jpeg")],
        )

    content = provider.call_args.args[0][-1]["content"]
    assert answer == "ok"
    assert sum(part.get("type") == "image_url" for part in content) == 2
    assert any(part.get("text") == "SKU X" for part in content)


@pytest.mark.parametrize("channel", ["facebook", "instagram", "telegram", "zalo", "tiktok", "shopee"])
def test_image_product_match_route_is_shared_by_all_supported_channels(channel):
    db = Mock()
    conversation = SimpleNamespace(bot_mode="auto", customer_id=8, resolution_outcome=None)
    db.query.return_value.filter.return_value.first.side_effect = [None, conversation]
    product = SimpleNamespace(
        id=91,
        sku="SHIRT-PINK-01",
        name="Áo sơ mi cotton hồng",
        price=199000,
        stock_quantity=5,
        reserved_quantity=1,
    )
    with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
        patch("app.services.auto_reply_service.is_business_open", return_value=True), \
        patch("app.services.auto_reply_service._latest_inbound_image_url", return_value="https://cdn.example/photo.jpg"), \
        patch("app.services.auto_reply_service._download_meta_image", return_value=(b"photo", "image/jpeg")), \
        patch("app.services.auto_reply_service.customer_order_reply", return_value=None), \
        patch("app.services.product_pricing.combo_price_comparison_reply", return_value=None), \
        patch("app.services.auto_reply_service.record_quota_usage"), \
        patch("app.services.auto_reply_service._match_customer_image_to_product", return_value=(product, [product], "Áo sơ mi hồng")), \
        patch("app.services.auto_reply_service.send_text_reply") as send:
        assert process_rag_auto_reply(
            db=db,
            conversation_id=4,
            channel=channel,
            query_text="Khách gửi ảnh đính kèm. Hãy xem ảnh khi trả lời; nếu chưa có câu hỏi rõ, hỏi một câu làm rõ.",
            business_id=7,
        ) is True

    reply = send.call_args.kwargs["text"]
    assert "SHIRT-PINK-01" in reply
    assert "199.000" in reply
    assert "còn 4" in reply


def test_zalo_personal_accepts_image_only_and_rejects_empty_message():
    photo = ZaloPersonalIncoming(
        authorId="customer-1",
        threadId="thread-1",
        mediaType="image",
        mediaUrl="https://cdn.example/customer.jpg",
    )
    assert photo.message == ""
    assert photo.media_type == "image"

    with pytest.raises(ValueError):
        ZaloPersonalIncoming(authorId="customer-1", threadId="thread-1")
    with pytest.raises(ValueError, match="đường dẫn công khai"):
        ZaloPersonalIncoming(authorId="customer-1", threadId="thread-1", mediaType="image")


def test_catalog_image_url_requires_https():
    with pytest.raises(ValueError, match="HTTPS"):
        ProductCreate(sku="SKU-1", name="Áo", image_url="http://cdn.example/shirt.jpg")
    assert ProductCreate(sku="SKU-1", name="Áo", image_url="https://cdn.example/shirt.jpg").image_url == (
        "https://cdn.example/shirt.jpg"
    )


def test_image_fetch_rejects_private_or_non_https_urls_before_network_request():
    with patch("app.services.inbound_image_service.httpx.Client") as client:
        with pytest.raises(ValueError, match="public HTTPS"):
            download_inbound_image_url("http://127.0.0.1/image.jpg", channel_type="zalo")

    client.return_value.__enter__.return_value.stream.assert_not_called()
