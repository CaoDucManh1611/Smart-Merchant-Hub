import pytest
from unittest.mock import patch
from test_business_request import setup
from app.services.customer_collection_flow import is_order_intent, _parse_order_form_details
from app.services.catalog_overview import catalog_overview_kind
from app.schemas.payment import PaymentCreate, RefundCreate
from pydantic import ValidationError


@pytest.mark.parametrize('text', [
    'cho mình đặt với nha', 'bạn hãy cho mình mua 1 cái nha',
    'cho tôi 1 Sữa rửa mặt dịu nhẹ – Nâng cao',
    'tôi muốn đặt 1 Toner cấp ẩm – Tiêu chuẩn', 'lấy cho tôi 1 cái nha',
])
def test_purchase_paraphrases(text):
    assert is_order_intent(text)


def test_named_cod_purchase_is_order_intent():
    assert is_order_intent('Mình muốn mua 1 Toner cấp ẩm – Bộ đôi, thanh toán khi nhận hàng nhé.')


@pytest.mark.parametrize('text', ['tôi không muốn mua toner', 'cho tôi xem chi tiết sản phẩm toner'])
def test_not_a_purchase(text):
    assert not is_order_intent(text)


def test_unlabelled_cod_form():
    values, found, invalid = _parse_order_form_details(
        'Cao Đức Mạnh\n0900000022\nbuyer@example.com\nBình Chánh\nThanh toán khi nhận hàng',
        ['name', 'phone', 'email', 'address', 'payment_method'], fallback_field='name')
    assert found and not invalid
    assert values['payment_method'] == 'cod'
    assert values['address'] == 'Bình Chánh'
    assert values['name'] == 'Cao Đức Mạnh'


@pytest.mark.parametrize('text', [
    'hello shop cua ban co j',
    'gom nhung gi v',
    'shop kinh doanh gi vay',
    'cho minh hoi ban voi la shop cua ban dang buon ban ve gi vay nhi',
    'shop dang kinh doanh ve mat hang gi vay',
    'shop buon ban ve cai gi vay',
    'shop ban mat hang nao la chu dao',
])
def test_catalog_paraphrases(text):
    assert catalog_overview_kind(text) == 'products'


@pytest.mark.parametrize('text', [
    'bạn cho tôi biết tất cả sản phẩm hiện có ở shop được không',
    'bạn có những sản phẩm nào',
    'cho mình xem danh sách sản phẩm đang bán',
    'tôi muốn xem tất cả các sản phẩm có trong shop bạn',
])
def test_explicit_full_product_list_is_distinct_from_shop_business_overview(text):
    assert catalog_overview_kind(text) == 'product_list'


def test_named_product_group_paraphrase_is_catalog_overview():
    assert catalog_overview_kind('tôi muốn tìm hiểu rõ hơn về các loại serum đi') == 'product_group'
    assert catalog_overview_kind('các loại serum đang có trong shop') == 'product_group'
    assert catalog_overview_kind('các loại son có trong shop') == 'product_group'
    assert catalog_overview_kind('thì có những loại serum nào') == 'product_group'
    assert catalog_overview_kind('những sản phẩm serum hiện tại đang có trong shop') == 'product_group'
    assert catalog_overview_kind('shop có những loại toner nào') == 'product_group'


def test_catalog_overview_groups_product_variants_for_customer_facing_answer(setup):
    from app.models.sales import Product
    from app.services.catalog_overview import render_catalog_overview

    db, conversation, *_ = setup
    db.add_all([
        Product(business_id=1, name='Toner cấp ẩm – Tiêu chuẩn', sku='TONER-STD',
                price=142000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Toner cấp ẩm – Bộ đôi', sku='TONER-DUO',
                price=284000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Sữa rửa mặt dịu nhẹ – Tiêu chuẩn', sku='WASH-STD',
                price=119000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Sữa rửa mặt dịu nhẹ – Nâng cao', sku='WASH-PRO',
                price=199000, stock_quantity=10, status='active'),
    ])
    db.commit()

    reply = render_catalog_overview(db, 1, 'products')

    assert 'Toner cấp ẩm' in reply
    assert 'Sữa rửa mặt dịu nhẹ' in reply
    assert 'Toner cấp ẩm – Tiêu chuẩn' not in reply
    assert 'Toner cấp ẩm – Bộ đôi' not in reply
    assert 'các nhóm chính' in reply.lower()


def test_explicit_product_list_shows_every_active_goods_variant(setup):
    from app.models.sales import Product
    from app.services.catalog_overview import render_catalog_overview

    db, *_ = setup
    db.add_all([
        Product(business_id=1, name='Serum niacinamide – Tiêu chuẩn', sku='SERUM-STD',
                price=180000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Serum niacinamide – Nâng cao', sku='SERUM-PRO',
                price=250000, stock_quantity=8, status='active'),
        Product(business_id=1, name='Toner cấp ẩm – Tiêu chuẩn', sku='TONER-STD',
                price=142000, stock_quantity=12, status='active'),
        Product(business_id=1, name='Serum đã ngừng bán', sku='SERUM-OFF',
                price=100000, stock_quantity=0, status='inactive'),
    ])
    db.commit()

    reply = render_catalog_overview(db, 1, 'product_list')

    assert 'Hàng thử' in reply
    assert 'Serum niacinamide – Tiêu chuẩn' in reply
    assert 'Serum niacinamide – Nâng cao' in reply
    assert 'Toner cấp ẩm – Tiêu chuẩn' in reply
    assert 'Serum đã ngừng bán' not in reply
    assert 'Máy ảnh thử' not in reply
    assert 'các nhóm chính' not in reply.lower()


def test_product_group_query_lists_matching_variants_without_recommendation_language(setup):
    from app.models.sales import Product
    from app.services.catalog_overview import render_catalog_overview

    db, *_ = setup
    db.add_all([
        Product(business_id=1, name='Serum niacinamide – Tiêu chuẩn', sku='SERUM-STD',
                price=180000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Serum niacinamide – Nâng cao', sku='SERUM-PRO',
                price=250000, stock_quantity=8, status='active'),
        Product(business_id=1, name='Toner cấp ẩm – Tiêu chuẩn', sku='TONER-STD',
                price=142000, stock_quantity=12, status='active'),
    ])
    db.commit()

    reply = render_catalog_overview(
        db, 1, 'product_group', query='những sản phẩm serum hiện tại đang có trong shop',
    )

    assert 'Serum niacinamide – Tiêu chuẩn' in reply
    assert 'Serum niacinamide – Nâng cao' in reply
    assert 'Toner cấp ẩm' not in reply
    assert 'gợi ý' not in reply.lower()


def test_shop_business_overview_is_deterministic_without_llm(setup):
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('catalog overview must not need the model')):
        result = graph_reply(
            db, business_id=1, conversation=conversation,
            query='shop buôn bán về cái gì vậy?', job_key='shop-business-overview',
        )

    assert result.status == 'catalog_overview'
    assert 'Hàng thử' in result.prompt
    assert 'shop hiện đang kinh doanh' in result.prompt.lower()


@pytest.mark.parametrize('query', [
    'bạn cho tôi biết tất cả sản phẩm hiện có ở shop được không',
    'tôi muốn xem tất cả các sản phẩm có trong shop bạn',
])
def test_full_product_list_graph_returns_all_variants_without_recommendations(setup, query):
    from app.models.sales import Product
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    db.add_all([
        Product(business_id=1, name='Serum niacinamide – Tiêu chuẩn', sku='SERUM-STD',
                price=180000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Serum niacinamide – Nâng cao', sku='SERUM-PRO',
                price=250000, stock_quantity=8, status='active'),
    ])
    db.commit()

    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('full product listing must not invoke recommendations')):
        result = graph_reply(
            db, business_id=1, conversation=conversation,
            query=query,
            job_key='all-products-list',
        )

    assert result.status == 'catalog_overview'
    assert 'Hàng thử' in result.prompt
    assert 'Serum niacinamide – Tiêu chuẩn' in result.prompt
    assert 'Serum niacinamide – Nâng cao' in result.prompt
    assert 'các nhóm chính' not in result.prompt.lower()


@pytest.mark.parametrize(('query', 'included_name', 'excluded_name'), [
    ('thì có những loại serum nào', 'Serum niacinamide – Tiêu chuẩn', 'Toner cấp ẩm'),
    ('những sản phẩm serum hiện tại đang có trong shop', 'Serum niacinamide – Nâng cao', 'Toner cấp ẩm'),
    ('shop có những loại toner nào', 'Toner cấp ẩm – Tiêu chuẩn', 'Serum niacinamide'),
])
def test_product_group_question_graph_lists_matching_variants_not_recommendations(
    setup, query, included_name, excluded_name,
):
    from app.models.sales import Product
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    db.add_all([
        Product(business_id=1, name='Serum niacinamide – Tiêu chuẩn', sku='SERUM-STD',
                price=180000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Serum niacinamide – Nâng cao', sku='SERUM-PRO',
                price=250000, stock_quantity=8, status='active'),
        Product(business_id=1, name='Toner cấp ẩm – Tiêu chuẩn', sku='TONER-STD',
                price=142000, stock_quantity=12, status='active'),
    ])
    db.commit()

    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('category browsing must not invoke recommendations')):
        result = graph_reply(
            db, business_id=1, conversation=conversation,
            query=query,
            job_key='serum-group-all-products',
        )

    assert result.status == 'catalog_overview'
    assert included_name in result.prompt
    assert excluded_name not in result.prompt
    assert 'gợi ý' not in result.prompt.lower()


def test_named_product_group_browse_lists_only_matching_active_products(setup):
    from app.models.sales import Product
    from app.services.catalog_overview import render_catalog_overview

    db, *_ = setup
    db.add_all([
        Product(business_id=1, name='Serum niacinamide – Tiêu chuẩn', sku='SERUM-STD',
                price=180000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Serum niacinamide – Nâng cao', sku='SERUM-PRO',
                price=250000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Toner cấp ẩm – Tiêu chuẩn', sku='TONER-STD',
                price=142000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Serum đã ngừng bán', sku='SERUM-OFF',
                price=100000, stock_quantity=10, status='inactive'),
        Product(business_id=2, name='Serum của shop khác', sku='FOREIGN-SERUM',
                price=100000, stock_quantity=10, status='active'),
    ])
    db.commit()

    reply = render_catalog_overview(
        db, 1, 'product_group', query='các loại serum đang có trong shop',
    )

    assert 'Serum niacinamide – Tiêu chuẩn' in reply
    assert 'Serum niacinamide – Nâng cao' in reply
    assert 'Toner cấp ẩm' not in reply
    assert 'Serum đã ngừng bán' not in reply
    assert 'shop khác' not in reply


def test_product_group_browse_is_deterministic_without_llm(setup):
    from app.models.sales import Product
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    db.add_all([
        Product(business_id=1, name='Serum niacinamide – Tiêu chuẩn', sku='SERUM-STD',
                price=180000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Toner cấp ẩm – Tiêu chuẩn', sku='TONER-STD',
                price=142000, stock_quantity=10, status='active'),
    ])
    db.commit()
    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('product group browse must not need the model')):
        result = graph_reply(
            db, business_id=1, conversation=conversation,
            query='các loại serum đang có trong shop',
            job_key='serum-group-browse',
        )

    assert result.status == 'catalog_overview'
    assert 'Serum niacinamide – Tiêu chuẩn' in result.prompt
    assert 'Toner cấp ẩm' not in result.prompt


def test_son_group_browse_is_deterministic_without_llm(setup):
    from app.models.sales import Product
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    db.add_all([
        Product(business_id=1, name='Son dưỡng môi – Tiêu chuẩn', sku='LIP-STD',
                price=99000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Son dưỡng môi – Bộ đôi', sku='LIP-DUO',
                price=179000, stock_quantity=10, status='active'),
        Product(business_id=1, name='Serum niacinamide – Tiêu chuẩn', sku='SERUM-STD',
                price=180000, stock_quantity=10, status='active'),
    ])
    db.commit()
    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('category browse must not invoke recommendations')):
        result = graph_reply(
            db, business_id=1, conversation=conversation,
            query='các loại son có trong shop', job_key='lip-group-browse',
        )

    assert result.status == 'catalog_overview'
    assert 'Son dưỡng môi – Tiêu chuẩn' in result.prompt
    assert 'Son dưỡng môi – Bộ đôi' in result.prompt
    assert 'Serum niacinamide' not in result.prompt


def test_service_menu_lists_only_active_appointment_services_with_price_and_duration(setup):
    from app.models.industry_modules import AppointmentService
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    db.add(AppointmentService(
        business_id=1,
        name='Tư vấn chăm sóc da',
        price=200000,
        duration_minutes=45,
        is_active=True,
    ))
    db.add(AppointmentService(
        business_id=1,
        name='Dịch vụ đã ngừng',
        price=50000,
        duration_minutes=15,
        is_active=False,
    ))
    db.commit()

    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('service listing must use appointment services directly')):
        result = graph_reply(
            db,
            business_id=1,
            conversation=conversation,
            query='Shop hiện đang cung cấp những dịch vụ nào? Hãy liệt kê tên dịch vụ, giá tiền và thời lượng thực hiện',
            job_key='service-menu-with-duration',
        )

    assert result.status == 'service_catalog_overview'
    assert 'Tư vấn chăm sóc da' in result.prompt
    assert '200.000 đồng' in result.prompt
    assert '45 phút' in result.prompt
    assert 'Dịch vụ thử' in result.prompt
    assert '150.000 đồng' in result.prompt
    assert '30 phút' in result.prompt
    assert 'Toner' not in result.prompt
    assert 'Dịch vụ đã ngừng' not in result.prompt


def test_named_service_detail_bypasses_overlapping_product_names(setup):
    from app.models.industry_modules import AppointmentService
    from app.models.sales import Product
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    service = db.query(AppointmentService).filter_by(business_id=1, name='Dịch vụ thử').one()
    service.name = 'kem khach 1 1'
    service.price = 300000
    service.duration_minutes = 60
    db.add_all([
        Product(business_id=1, name='Kem dưỡng phục hồi – Tiêu chuẩn', sku='CREAM-STD',
                price=188000, stock_quantity=18, status='active'),
        Product(business_id=1, name='Kem chống nắng – Tiêu chuẩn', sku='SUN-STD',
                price=211000, stock_quantity=21, status='active'),
    ])
    db.commit()

    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('named service facts must bypass product search and LLM')):
        result = graph_reply(
            db, business_id=1, conversation=conversation,
            query='Tôi muốn tìm hiểu kỹ hơn về dịch vụ kem khach 1 1. Dịch vụ này có giá bao nhiêu và thực hiện trong khoảng bao lâu?',
            job_key='named-service-detail',
        )

    assert result.status == 'service_catalog_answer'
    assert 'kem khach 1 1' in result.prompt
    assert '300.000 đồng' in result.prompt
    assert '60 phút' in result.prompt
    assert 'Kem dưỡng phục hồi' not in result.prompt
    assert 'Kem chống nắng' not in result.prompt
    assert 'Bạn xác nhận đặt hàng' not in result.prompt


def test_service_duration_budget_returns_only_services_that_fit(setup):
    from app.models.industry_modules import AppointmentService
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    service = db.query(AppointmentService).filter_by(business_id=1, name='Dịch vụ thử').one()
    service.name = 'kem khach 1 1'
    service.price = 300000
    service.duration_minutes = 60
    db.add(AppointmentService(
        business_id=1, name='Tư vấn nhanh', price=100000,
        duration_minutes=20, is_active=True,
    ))
    db.commit()

    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('service duration filter must not need the model')):
        result = graph_reply(
            db, business_id=1, conversation=conversation,
            query='Nếu tôi chỉ có khoảng 30 phút thì có dịch vụ nào phù hợp không?',
            job_key='service-duration-fit',
        )

    assert result.status == 'service_catalog_answer'
    assert 'Tư vấn nhanh' in result.prompt
    assert '100.000 đồng' in result.prompt
    assert '20 phút' in result.prompt
    assert 'kem khach 1 1' not in result.prompt


def test_service_price_confirmation_does_not_invent_all_inclusive_fees(setup):
    from app.models.industry_modules import AppointmentService
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    service = db.query(AppointmentService).filter_by(business_id=1, name='Dịch vụ thử').one()
    service.name = 'kem khach 1 1'
    service.price = 300000
    service.duration_minutes = 60
    db.commit()

    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('service price fact must be deterministic')):
        result = graph_reply(
            db, business_id=1, conversation=conversation,
            query='Dịch vụ kem khach 1 1 có giá 300.000 đồng đúng không? Giá này đã bao gồm toàn bộ chi phí chưa?',
            job_key='service-fee-confirmation',
        )

    assert result.status == 'service_catalog_answer'
    assert '300.000 đồng' in result.prompt
    assert '60 phút' in result.prompt
    assert 'chưa thể xác nhận' in result.prompt
    assert 'Kem dưỡng phục hồi' not in result.prompt


def test_service_lowest_price_and_price_table_use_appointment_catalog(setup):
    from app.models.industry_modules import AppointmentService
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    service = db.query(AppointmentService).filter_by(business_id=1, name='Dịch vụ thử').one()
    service.name = 'kem khach 1 1'
    service.price = 300000
    service.duration_minutes = 60
    db.add(AppointmentService(
        business_id=1, name='Tư vấn nhanh', price=100000,
        duration_minutes=20, is_active=True,
    ))
    db.commit()

    for query, job_key, expected_names in (
        ('Tôi muốn biết dịch vụ nào có mức giá thấp nhất trong danh mục hiện tại',
         'service-cheapest', ('Tư vấn nhanh',)),
        ('Hãy tổng hợp lại bảng giá các dịch vụ để tôi dễ so sánh trước khi quyết định',
         'service-price-table', ('kem khach 1 1', 'Tư vấn nhanh')),
    ):
        with patch('app.services.conversation_graph.call_llm',
                   side_effect=AssertionError('service price comparisons must not use product recommendations')):
            result = graph_reply(
                db, business_id=1, conversation=conversation, query=query, job_key=job_key,
            )
        assert result.status == 'service_catalog_answer'
        for expected_name in expected_names:
            assert expected_name in result.prompt
        assert 'Kem dưỡng phục hồi' not in result.prompt


def test_service_shorter_alternative_does_not_claim_similarity_without_catalog_evidence(setup):
    from app.models.industry_modules import AppointmentService
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    service = db.query(AppointmentService).filter_by(business_id=1, name='Dịch vụ thử').one()
    service.name = 'kem khach 1 1'
    service.price = 300000
    service.duration_minutes = 60
    db.commit()

    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('service duration comparison must be deterministic')):
        result = graph_reply(
            db, business_id=1, conversation=conversation,
            query='Shop có dịch vụ nào tương tự kem khach 1 1 nhưng thời lượng ngắn hơn không?',
            job_key='service-shorter-alternative',
        )

    assert result.status == 'service_catalog_answer'
    assert 'kem khach 1 1' in result.prompt
    assert '60 phút' in result.prompt
    assert 'chưa có dịch vụ nào ngắn hơn' in result.prompt


def _seed_service_chat_context(setup):
    from app.models.industry_modules import AppointmentService
    from app.models.message import Message

    db, conversation, *_ = setup
    main_service = db.query(AppointmentService).filter_by(business_id=1, name='Dịch vụ thử').one()
    main_service.name = 'kem khach 1 1'
    main_service.price = 300000
    main_service.duration_minutes = 60
    cheaper_service = AppointmentService(
        business_id=1, name='thay nhong sen dia cho Wave Alpha 110',
        price=180000, duration_minutes=120, is_active=True,
    )
    db.add(cheaper_service)
    db.add(Message(
        conversation_id=conversation.id,
        channel=conversation.channel,
        direction='outbound',
        sender_type='bot',
        content='Theo danh mục hiện tại: kem khach 1 1: 300.000 đồng, thời lượng khoảng 60 phút.',
    ))
    db.commit()
    return db, conversation


def test_broad_service_inquiry_lists_active_services_instead_of_claiming_unconfigured(setup):
    from app.models.industry_modules import AppointmentService
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    service = db.query(AppointmentService).filter_by(
        business_id=1, name='Dịch vụ thử',
    ).one()
    service.name = 'kem khach 1 1'
    service.price = 300000
    service.duration_minutes = 60
    db.add(AppointmentService(
        business_id=1, name='thay nhong sen dia cho Wave Alpha 110',
        price=180000, duration_minutes=120, is_active=True,
    ))
    db.commit()

    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('broad service inquiry should use active appointment services')):
        result = graph_reply(
            db, business_id=1, conversation=conversation,
            query='Bên mình có làm dịch vụ chăm sóc này không nhỉ? Tôi muốn tham khảo giá trước.',
            job_key='broad-service-inquiry',
        )

    assert result.status in {'service_catalog_answer', 'service_catalog_overview'}
    assert 'kem khach 1 1' in result.prompt
    assert '300.000 đồng' in result.prompt
    assert 'thay nhong sen dia cho Wave Alpha 110' in result.prompt
    assert 'chưa cấu hình dịch vụ' not in result.prompt.lower()


@pytest.mark.parametrize(('query', 'expected', 'unexpected'), [
    ('Giá của dịch vụ đó là bao nhiêu', '300.000 đồng', 'chưa tìm thấy dịch vụ'),
    ('Nếu tôi muốn sử dụng hai lần thì tổng chi phí là bao nhiêu', '600.000 đồng', 'tạo lịch'),
    ('Dịch vụ nào tương tự nhưng giá thấp hơn không', '180.000 đồng', 'Kem dưỡng phục hồi'),
    ('Tôi muốn tìm một dịch vụ có thời gian thực hiện khoảng một tiếng, shop có không?', '60 phút', 'chưa cấu hình'),
    ('Dịch vụ nào bên bạn đang có giá khoảng 300 nghìn vậy?', 'kem khach 1 1', 'Toner cấp ẩm'),
    ('Có thể giải thích rõ hơn dịch vụ mà bạn vừa giới thiệu cho tôi không?', 'kem khach 1 1', 'Bạn muốn mua'),
])
def test_service_followups_keep_service_context_and_never_route_to_products(setup, query, expected, unexpected):
    from app.services.conversation_graph import graph_reply

    db, conversation = _seed_service_chat_context(setup)
    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('service followup must be answered before product routing')):
        result = graph_reply(
            db, business_id=1, conversation=conversation,
            query=query, job_key='service-context-followup',
        )

    assert result.status == 'service_catalog_answer'
    assert expected.lower() in result.prompt.lower()
    assert unexpected.lower() not in result.prompt.lower()


def test_service_followup_does_not_reuse_context_older_than_30_minutes(setup):
    from datetime import datetime, timedelta, timezone
    from app.models.message import Message
    from app.services.catalog_overview import render_service_catalog_reply

    db, conversation = _seed_service_chat_context(setup)
    latest = db.query(Message).filter_by(conversation_id=conversation.id).one()
    latest.received_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

    result = render_service_catalog_reply(
        db, 1, 'Nếu tôi muốn sử dụng hai lần thì tổng chi phí là bao nhiêu',
        conversation_id=conversation.id,
    )
    assert result is None


def test_order_list_question_is_answered_from_customer_scoped_orders_before_llm(setup):
    from app.services.conversation_graph import graph_reply

    db, conversation, *_ = setup
    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('customer order lookup must not need the model')):
        result = graph_reply(
            db,
            business_id=1,
            conversation=conversation,
            query='tôi đang có đơn hàng gì',
            job_key='customer-order-list',
        )

    # This fixture has no orders; the deterministic path should answer that
    # clearly instead of falling through to a generic knowledge-base error.
    assert result.status == 'customer_order_list'
    assert 'chưa thấy đơn hàng nào' in result.prompt.lower()


@pytest.mark.parametrize('model', [PaymentCreate, RefundCreate])
def test_vnd_rejects_fractional_money(model):
    with pytest.raises(ValidationError):
        model(idempotency_key='test', amount='0.06', method='manual')
    assert model(idempotency_key='test', amount='357000', method='manual').amount == 357000


@pytest.mark.parametrize('text', [
    'cho tôi 1 Sữa rửa mặt dịu nhẹ – Nâng cao',
    'tôi muốn đặt 1 Sữa rửa mặt dịu nhẹ – Nâng cao',
    'đặt giúp mình 1 Sữa rửa mặt dịu nhẹ – Nâng cao',
    'shop lên đơn 1 Sữa rửa mặt dịu nhẹ – Nâng cao cho em',
    'mình chốt một Sữa rửa mặt dịu nhẹ – Nâng cao nhé',
])
def test_named_purchase_graph_needs_no_llm(setup, text):
    from app.services.conversation_graph import graph_reply
    db, conversation, product, *_ = setup
    product.name = 'Sữa rửa mặt dịu nhẹ – Nâng cao'
    db.commit()
    with patch('app.services.conversation_graph.call_llm', side_effect=AssertionError('known purchase should be deterministic')):
        result = graph_reply(db, business_id=1, conversation=conversation, query=text, job_key='natural-purchase')
    assert product.name in result.prompt
    assert '200.000' in result.prompt


def test_named_purchase_starts_order_confirmation_instead_of_only_reporting_stock(setup):
    from app.services.conversation_graph import graph_reply

    db, conversation, product, *_ = setup
    product.name = 'Toner cấp ẩm – Nhỏ gọn'
    product.price = 284000
    product.stock_quantity = 17
    product.reserved_quantity = 0
    db.commit()

    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('a named purchase should enter deterministic checkout')):
        result = graph_reply(
            db, business_id=1, conversation=conversation,
            query='tôi muốn đặt 1 toner cấp ẩm nhỏ gọn đi',
            job_key='named-toner-purchase',
        )

    assert result.status == 'pending'
    assert 'Toner cấp ẩm – Nhỏ gọn' in result.prompt
    if result.current_field == 'quantity':
        assert 'bao nhiêu' in result.prompt
    else:
        assert '284.000' in result.prompt
        assert 'xác nhận' in result.prompt.lower()


@pytest.mark.parametrize('text', ['cho tôi đặt 1 cái đi', 'cho tôi đặt hàng', 'cho mình đặt với nha'])
def test_short_purchase_followup_uses_recent_stock_item(setup, text):
    from app.models.message import Message
    from app.services.customer_collection_flow import advance_customer_collection

    db, conversation, product, *_ = setup
    product.name = 'Toner cấp ẩm – Nhỏ gọn'
    product.price = 284000
    product.stock_quantity = 17
    product.reserved_quantity = 0
    db.add(Message(
        conversation_id=conversation.id, channel=conversation.channel,
        sender_type='bot', direction='outbound',
        content='Dạ, Toner cấp ẩm – Nhỏ gọn hiện còn 17 sản phẩm ạ.',
    ))
    db.commit()

    from app.services.product_resolver import resolve_product_mentions
    assert resolve_product_mentions(
        db, business_id=1, conversation_id=conversation.id, text=text,
    ) == [product]

    result = advance_customer_collection(
        db, business_id=1, customer_id=conversation.customer_id,
        conversation_id=conversation.id, source_channel=conversation.channel, text=text,
    )

    assert result is not None
    assert result.status == 'pending'
    assert 'Toner cấp ẩm – Nhỏ gọn' in result.prompt
    if result.current_field == 'quantity':
        assert 'bao nhiêu' in result.prompt
    else:
        assert '284.000' in result.prompt
        assert 'xác nhận' in result.prompt.lower()


@pytest.mark.parametrize('text', ['cho tôi đặt 1 cái đi', 'cho tôi đặt hàng'])
def test_graph_routes_short_purchase_followup_to_checkout(setup, text):
    from app.models.message import Message
    from app.services.conversation_graph import graph_reply

    db, conversation, product, *_ = setup
    product.name = 'Toner cấp ẩm – Nhỏ gọn'
    product.price = 284000
    product.stock_quantity = 17
    product.reserved_quantity = 0
    db.add(Message(
        conversation_id=conversation.id, channel=conversation.channel,
        sender_type='bot', direction='outbound',
        content='Dạ, Toner cấp ẩm – Nhỏ gọn hiện còn 17 sản phẩm ạ.',
    ))
    db.commit()

    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('a stock-item followup should enter deterministic checkout')):
        result = graph_reply(
            db, business_id=1, conversation=conversation, query=text,
            job_key='short-toner-purchase-followup',
        )

    assert result.status == 'pending'
    if text == 'cho tôi đặt hàng':
        assert result.current_field == 'quantity'
        assert 'bao nhiêu' in result.prompt
        return
    assert 'Toner cấp ẩm – Nhỏ gọn' in result.prompt
    if result.current_field == 'quantity':
        assert 'bao nhiêu' in result.prompt
    else:
        assert '284.000' in result.prompt
        assert 'xác nhận' in result.prompt.lower()


def test_product_detail_from_catalog_without_llm(setup):
    from app.services.conversation_graph import graph_reply
    db, conversation, product, *_ = setup
    product.name = 'Sữa rửa mặt dịu nhẹ – Nâng cao'
    product.description = 'Sản phẩm rửa mặt, chai 100 ml.'
    db.commit()
    with patch('app.services.conversation_graph.call_llm', side_effect=AssertionError('catalog detail should be deterministic')):
        result = graph_reply(db, business_id=1, conversation=conversation,
            query='cho tôi xem chi tiết về sản phẩm Sữa rửa mặt dịu nhẹ – Nâng cao', job_key='detail')
    assert product.name in result.prompt
    assert '100 ml' in result.prompt


@pytest.mark.parametrize('text', ['cho mình đặt với nha', 'lấy cho tôi 1 cái nha', 'bạn hãy cho mình mua 1 cái nha'])
def test_purchase_keeps_unique_recent_product(setup, text):
    from app.models.message import Message
    from app.services.customer_collection_flow import advance_customer_collection
    db, conversation, product, *_ = setup
    db.add(Message(conversation_id=conversation.id, channel=conversation.channel,
        sender_type='bot', direction='outbound', content=f'{product.name}: còn 10 sản phẩm.'))
    db.commit()
    result = advance_customer_collection(db, business_id=1, customer_id=conversation.customer_id,
        conversation_id=conversation.id, source_channel=conversation.channel, text=text)
    assert product.name in result.prompt
    assert '200.000' in result.prompt


@pytest.mark.parametrize('text', ['Thôi chưa mua nữa, mình muốn xem shop có gì trước đã.',
    'Mình không muốn đặt nữa nha, để hôm khác.', 'Đừng chốt đơn nhé mình đang xem thôi'])
def test_long_rejection_closes_quote_without_collecting_info(setup, text):
    from app.services.customer_collection_flow import advance_customer_collection
    from app.models.customer_collection import CustomerCollectionSession
    from app.models.sales import Order
    db, conversation, product, *_ = setup
    def turn(query):
        return advance_customer_collection(db, business_id=1, customer_id=conversation.customer_id,
            conversation_id=conversation.id, source_channel=conversation.channel, text=query)
    turn(f'Mình mua 1 {product.name}')
    reply = turn(text)
    assert reply.status == 'abandoned'
    assert db.query(CustomerCollectionSession).one().status == 'abandoned'
    assert db.query(Order).count() == 0


@pytest.mark.parametrize('query', [
    'Chào shop, bên mình có gì vậy?', 'cho em xem hàng đang bán',
    'Bên bạn đang có mặt hàng nào?', 'shop kinh doanh những sản phẩm nào',
])
def test_opening_variants_read_live_catalog_without_llm(setup, query):
    from app.services.conversation_graph import graph_reply
    db, conversation, product, *_ = setup
    with patch('app.services.conversation_graph.call_llm', side_effect=AssertionError('catalog opening')):
        result = graph_reply(db, business_id=1, conversation=conversation, query=query, job_key='opening')
    assert product.name in result.prompt


@pytest.mark.parametrize('query', ['Loại này có tác dụng gì vậy?', 'Sản phẩm này dùng thế nào?', 'Cho mình xem chi tiết trước đã'])
def test_detail_question_during_quote_does_not_accept_or_lose_cart(setup, query):
    from app.services.customer_collection_flow import advance_customer_collection
    from app.models.customer_collection import CustomerCollectionSession
    db, conversation, product, *_ = setup
    def turn(text):
        return advance_customer_collection(db, business_id=1, customer_id=conversation.customer_id,
            conversation_id=conversation.id, source_channel=conversation.channel, text=text)
    turn(f'Mình mua 2 {product.name}')
    assert turn(query) is None
    session = db.query(CustomerCollectionSession).one()
    assert session.purpose == 'order_confirmation'
    assert session.collected_fields['quantity'] == 2
    result = turn('Ừ được rồi, lên đơn giúp mình')
    assert 'Tên người nhận:' in result.prompt
    assert session.collected_fields['quantity'] == 2


@pytest.mark.parametrize('query,quantity', [
    ('Cho mình 2 chai nhé', 2), ('Vậy mình lấy 2 chai nha', 2),
    ('đổi thành 3 cái giúp mình', 3), ('Mình mua thêm 2 cái nữa', 3),
])
def test_conversational_quantity_edits(setup, query, quantity):
    from app.services.customer_collection_flow import advance_customer_collection
    from app.models.customer_collection import CustomerCollectionSession
    db, conversation, product, *_ = setup
    def turn(text):
        return advance_customer_collection(db, business_id=1, customer_id=conversation.customer_id,
            conversation_id=conversation.id, source_channel=conversation.channel, text=text)
    turn(f'Mình mua 1 {product.name}')
    result = turn(query)
    session = db.query(CustomerCollectionSession).one()
    assert session.collected_fields['quantity'] == quantity
    assert session.purpose == 'order_confirmation'
    assert 'Tên người nhận:' not in result.prompt
    result = turn('Ừ được rồi, lên đơn giúp mình')
    assert 'Tên người nhận:' in result.prompt
    assert session.collected_fields['quantity'] == quantity


def test_variant_answer_selects_only_from_recent_options(setup):
    from app.models.sales import Product
    from app.models.message import Message
    from app.services.product_resolver import resolve_product
    db, conversation, product, *_ = setup
    product.name = 'Toner cấp ẩm – Tiêu chuẩn'
    other = Product(business_id=1, sku='TONER-PRO', name='Toner cấp ẩm – Nâng cao',
        price=300000, stock_quantity=10, reserved_quantity=0, status='active')
    unrelated = Product(business_id=1, sku='WASH-STD', name='Sữa rửa mặt – Tiêu chuẩn',
        price=100000, stock_quantity=10, reserved_quantity=0, status='active')
    db.add_all([other, unrelated]); db.flush()
    db.add(Message(conversation_id=conversation.id, channel=conversation.channel, sender_type='bot',
        direction='outbound', content=f'Shop có các mẫu:\n• {product.name}\n• {other.name}\nBạn chọn mẫu nào?'))
    db.commit()
    selected = resolve_product(db, business_id=1, conversation_id=conversation.id, text='Mình lấy bản tiêu chuẩn')
    assert selected.id == product.id


@pytest.mark.parametrize('query', ['Ừ, làm đơn cho em đi shop', 'Vâng, đặt giúp mình nhé', 'Được, mình đồng ý mua', 'Ừ', 'Vâng nhé', 'Dạ'])
def test_natural_approval_reaches_form(setup, query):
    from app.services.customer_collection_flow import advance_customer_collection
    db, conversation, product, *_ = setup
    def turn(text):
        return advance_customer_collection(db, business_id=1, customer_id=conversation.customer_id,
            conversation_id=conversation.id, source_channel=conversation.channel, text=text)
    turn(f'Mình mua 1 {product.name}')
    result = turn(query)
    assert 'Tên người nhận:' in result.prompt


def test_ambiguous_family_never_picks_arbitrary_variant(setup):
    from app.models.sales import Product
    from app.services.customer_collection_flow import advance_customer_collection
    from app.models.customer_collection import CustomerCollectionSession
    db, conversation, product, *_ = setup
    product.name = 'Toner cấp ẩm – Tiêu chuẩn'
    db.add(Product(business_id=1, sku='TONER-OTHER', name='Toner cấp ẩm – Nâng cao',
        price=300000, stock_quantity=10, reserved_quantity=0, status='active'))
    db.commit()
    result = advance_customer_collection(db, business_id=1, customer_id=conversation.customer_id,
        conversation_id=conversation.id, source_channel=conversation.channel, text='Mình muốn mua toner')
    assert db.query(CustomerCollectionSession).count() == 0
    assert result.status == 'product_clarification'
    assert 'Toner cấp ẩm – Tiêu chuẩn' in result.prompt
    assert 'Toner cấp ẩm – Nâng cao' in result.prompt
    assert 'Tên người nhận:' not in result.prompt


@pytest.mark.parametrize('query', ['shop ban nhung gi vay', 'Chào shop, bên mình có gì vậy?', 'gồm những gì v'])
def test_catalog_question_at_form_is_not_stored_as_customer_name(setup, query):
    from app.services.customer_collection_flow import advance_customer_collection
    from app.models.customer_collection import CustomerCollectionSession
    db, conversation, product, *_ = setup
    def turn(text):
        return advance_customer_collection(db, business_id=1, customer_id=conversation.customer_id,
            conversation_id=conversation.id, source_channel=conversation.channel, text=text)
    turn(f'Mình mua 1 {product.name}')
    turn('Đồng ý')
    assert turn(query) is None
    session = db.query(CustomerCollectionSession).one()
    assert session.status == 'abandoned'
    assert not session.collected_fields.get('name')


def test_quantity_price_question_with_no_purchase_uses_live_math_not_llm(setup):
    from app.services.conversation_graph import graph_reply
    from app.models.customer_collection import CustomerCollectionSession
    from app.models.sales import Order
    db, conversation, product, *_ = setup
    product.name = 'Sữa rửa mặt dịu nhẹ – Nhỏ gọn'
    db.commit()
    with patch('app.services.conversation_graph.call_llm', side_effect=AssertionError('price needs live math')):
        reply = graph_reply(db, business_id=1, conversation=conversation,
            query=f'Nếu mua 2 {product.name} thì tổng bao nhiêu? Mình chỉ hỏi giá, chưa đặt hàng.', job_key='quote-only')
    assert '400.000' in reply.prompt
    assert 'chưa tạo đơn hàng' in reply.prompt
    assert db.query(Order).count() == 0
    assert db.query(CustomerCollectionSession).count() == 0


@pytest.mark.parametrize('text', ['ok tao đặt nó', 'ok mình đặt nó', 'đặt sản phẩm đó'])
def test_graph_contextual_purchase_asks_quantity_then_quotes(setup, text):
    from app.models.message import Message
    from app.services.conversation_graph import graph_reply

    db, conversation, product, *_ = setup
    product.name = 'Toner cấp ẩm – Nhỏ gọn'
    product.price = 284000
    product.stock_quantity = 17
    product.reserved_quantity = 0
    db.add(Message(
        conversation_id=conversation.id, channel=conversation.channel,
        sender_type='bot', direction='outbound',
        content='Dạ, Toner cấp ẩm – Nhỏ gọn hiện còn 17 sản phẩm ạ.',
    ))
    db.commit()

    with patch('app.services.conversation_graph.call_llm',
               side_effect=AssertionError('a stock-item followup should enter deterministic checkout')):
        result = graph_reply(
            db, business_id=1, conversation=conversation, query=text,
            job_key='short-toner-purchase-followup',
        )

    assert result.current_field == 'quantity'
    assert 'bao nhiêu' in result.prompt
    result = graph_reply(db, business_id=1, conversation=conversation, query='2', job_key='quantity-answer')
    assert result.current_field == 'order_confirmation'
    assert '568.000' in result.prompt
    assert 'Toner cấp ẩm – Nhỏ gọn' in result.prompt


def test_variant_selection_stays_in_lip_group_when_quantity_exceeds_stock(setup):
    from app.models.message import Message
    from app.models.sales import Product
    from app.services.conversation_graph import graph_reply
    db,c,old,*_=setup
    old.name='Mặt nạ đất sét – Tiêu chuẩn'
    lip=Product(business_id=1,sku='LIP-REG',name='Son dưỡng môi – Tiêu chuẩn',price=280000,stock_quantity=5,reserved_quantity=0,status='active')
    other=Product(business_id=1,sku='LIP-REG-2',name='Son dưỡng môi – Nhỏ gọn',price=560000,stock_quantity=5,reserved_quantity=0,status='active')
    db.add_all([lip,other]);db.flush()
    db.add(Message(conversation_id=c.id,channel=c.channel,direction='outbound',sender_type='bot',content='Bạn muốn chọn phiên bản nào?\n• Son dưỡng môi – Tiêu chuẩn — 280.000 đồng\n• Son dưỡng môi – Nhỏ gọn — 560.000 đồng'))
    db.commit()
    a=graph_reply(db,business_id=1,conversation=c,query='bản tiêu chuẩn, đặt hàng luôn',job_key='lip-variant')
    assert a.current_field=='quantity'
    b=graph_reply(db,business_id=1,conversation=c,query='200',job_key='lip-quantity')
    assert 'Son dưỡng môi – Tiêu chuẩn' in b.prompt
    assert '200' in b.prompt
    assert 'Mặt nạ' not in b.prompt
