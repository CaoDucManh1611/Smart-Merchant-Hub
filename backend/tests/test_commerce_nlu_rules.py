from app.rag.prompt_builder import detect_reply_language
from app.services.auto_reply_service import (
    _product_hint,
    _requested_variant_tokens,
    _is_price_question,
    _is_product_fact_question,
    _is_specific_product_lookup,
    _fold_text,
)


def test_product_hint_keeps_vietnamese_accents_and_capacity():
    hint = _product_hint("Bình giữ nhiệt inox 600 ml Mây Nhà")
    assert "Bình" in hint and "600 ml" in hint
from app.services.customer_collection_flow import (
    _extract_quantity,
    is_price_quote_request,
    is_stock_query_request,
    _format_quote_prompt,
    _is_order_approval,
    _is_order_rejection,
    _is_quantity_only_update,
    _is_underspecified_purchase_request,
    is_greeting,
    is_order_intent,
)
from app.services.chatbot_agent import ESCALATION_TERMS
from app.services.customer_order_service import detect_customer_order_intent


def test_vietnamese_product_and_delivery_words_are_not_misread_as_price():
    assert not _is_product_fact_question("Điện gia dụng mẫu 01")
    assert not _is_product_fact_question("Đơn ORD-120 giao tới đâu rồi?")


def test_model_reference_allows_precise_product_price_and_detail_routes():
    text = "Mẫu 01 giá bao nhiêu?"
    assert _is_product_fact_question(text)
    assert _is_specific_product_lookup("Cho mình xem Điện gia dụng mẫu 01")
    assert _is_specific_product_lookup("Show me household appliance model 01")


def test_bare_price_question_remains_supported_without_matching_product_names():
    assert _is_price_question(_fold_text("Giá?"))
    assert not _is_price_question(_fold_text("Thiết bị gia dụng"))


def test_product_capacity_is_not_order_quantity():
    question = "Shop ơi, bình giữ nhiệt inox 600 ml Mây Nhà giá bao nhiêu ạ?"
    assert not is_price_quote_request(question)
    assert _extract_quantity(question) == 0


def test_how_many_left_is_stock_question_not_a_checkout_update():
    assert is_stock_query_request("Ấm đun siêu tốc 1.8 lít Mây Nhà hiện còn mấy chiếc ạ?")
    assert is_stock_query_request("Bình giữ nhiệt inox 600 ml còn bao nhiêu chiếc?")


def test_common_english_greetings_and_product_lookup_use_english_reply_language():
    assert is_greeting("Hi there")
    assert detect_reply_language("Hi there") == "en"
    assert detect_reply_language("Show me household appliance model 01") == "en"


def test_natural_order_tracking_phrase_is_recognized():
    assert detect_customer_order_intent("Đơn ORD-120 giao tới đâu rồi?") == "status"


def test_english_commerce_intents_and_safe_clarification_are_detected():
    assert _is_underspecified_purchase_request("Tôi muốn mua hàng")
    assert _is_underspecified_purchase_request("Lấy giúp mình 2 cái")
    assert _is_underspecified_purchase_request("I want to buy something")
    assert _is_underspecified_purchase_request("I'll take two, please")
    assert is_order_intent("I want one household appliance model 01")
    assert _extract_quantity("I want one household appliance model 01") == 1
    assert _is_quantity_only_update("Actually, make that 20")
    assert _is_quantity_only_update("Sửa thành 20 cái nhé")
    assert _extract_quantity("Sửa thành 20 cái nhé") == 20


def test_english_order_actions_and_staff_handoff_are_detected():
    assert detect_customer_order_intent("Where is order ORD-120 now?") == "status"
    assert detect_customer_order_intent("Please cancel order ORD-120") == "cancel"
    assert any(term in "can i speak to a person?" for term in ESCALATION_TERMS)


def test_variant_selection_is_explicit_for_stock_lookup():
    assert _requested_variant_tokens("Áo khoác Lona màu đen size M còn không?") == {"den", "m"}
    assert _requested_variant_tokens("Is the Lona jacket in black, size M, available?") == {"black", "m"}


def test_order_quote_uses_the_detected_reply_language():
    items = [{
        "product_name": "Household appliance model 01",
        "quantity": 3,
        "unit_price": "349000",
        "available": 20,
    }]
    english = _format_quote_prompt(items, language="en")
    assert "Would you like" in english and "₫1,047,000" in english
    assert "Bạn muốn" not in english
