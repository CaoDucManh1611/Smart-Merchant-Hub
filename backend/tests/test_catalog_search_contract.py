"""Synthetic catalog/workflow contracts; the shared harness selects the engine.

The default harness remaps SQLite URLs to disposable PostgreSQL schemas.
"""
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.database.bases import TenantBase
from app.models import Business, Conversation, Customer
from app.models.customer_collection import CustomerCollectionSession
from app.models.industry_modules import Appointment, AppointmentService
from app.models.sales import Order, OrderItem, Product
from app.schemas.business_profile import BusinessProfile
from app.services.business_request import advance_business_request, current_offerings
from app.services.catalog_search import get_current_offering, search_current_offerings
from app.tenancy.workspace_modules import save_workspace_config


@pytest.fixture(scope="module")
def catalog_engine():
    engine = create_engine("sqlite://")
    Business.metadata.create_all(engine)
    TenantBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def catalog_connection(catalog_engine):
    with catalog_engine.connect() as connection:
        transaction = connection.begin()
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN")
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def catalog(catalog_connection):
    # Workflow commits only release a savepoint; each test's outer transaction
    # rolls back all seed and workflow writes in the disposable test schema.
    with Session(catalog_connection, join_transaction_mode="create_savepoint") as db:
        db.add_all([Business(id=1, name="Synthetic A", slug="catalog-a"),
                    Business(id=2, name="Synthetic B", slug="catalog-b")])
        db.add_all(Product(id=i, business_id=1, sku=f"CAM-{i}", name="Máy ảnh phổ thông",
                           price=900000, stock_quantity=10,
                           metadata_={"offering_type": "goods", "attributes": {"color": "blue", "size": "S"}})
                   for i in range(1, 131))
        db.add_all(AppointmentService(id=i, business_id=1, name="Dịch vụ phổ thông", price=900000, duration_minutes=30)
                   for i in range(1, 131))
        db.add_all([
            Product(id=501, business_id=1, sku="LATE-501", name="Máy ảnh Vision 2023", price=120000,
                    stock_quantity=10, reserved_quantity=3,
                    metadata_={"offering_type": "goods", "aliases": ["bí danh độc quyền"],
                               "attributes": {"color": ["red", "black"], "size": "M", "vehicle_model": "Vision", "vehicle_year": 2023}}),
            Product(id=502, business_id=1, sku="LATE-502", name="Máy ảnh thuê", price=150000, stock_quantity=2,
                    metadata_={"offering_type": "rental", "billing_unit": "ngày", "attributes": {"color": "red", "size": "M"}}),
            Product(id=503, business_id=1, sku="LATE-503", name="Tư vấn ảnh", price=80000, stock_quantity=0,
                    metadata_={"offering_type": "service"}),
            Product(id=601, business_id=2, sku="LATE-501", name="PRIVATE", price=1, stock_quantity=999),
            Product(id=602, business_id=1, sku="INACTIVE", name="Máy ảnh Vision 2023", price=1, status="inactive"),
            AppointmentService(id=501, business_id=1, name="Chăm sóc chuyên sâu", price=180000, duration_minutes=90),
            AppointmentService(id=601, business_id=2, name="PRIVATE SERVICE", price=1),
            AppointmentService(id=602, business_id=1, name="Chăm sóc chuyên sâu", price=1, is_active=False),
        ])
        customer = Customer(business_id=1, channel="facebook", external_user_id="synthetic-catalog")
        db.add(customer)
        db.flush()
        conversation = Conversation(business_id=1, customer_id=customer.id, channel="facebook")
        db.add(conversation)
        save_workspace_config(db, 1, {
            "business_type": "mixed",
            "enabled_modules": ["retail", "appointments"],
            "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS", "APPOINTMENT_TOOLS"],
        })
        db.commit()
        yield db, conversation


def refs(items):
    return [item["ref"] for item in items]


@pytest.mark.parametrize("query,options,expected", [
    ("SKU LATE-501", {}, "product:501"),
    ("mua LATE-501 máy ảnh", {}, "product:501"),
    ("bí danh độc quyền", {}, "product:501"),
    ("Tôi muốn mua Máy ảnh Vision 2023", {}, "product:501"),
    ("Mua bí danh độc quyền máy ảnh", {}, "product:501"),
    ("Chăm sóc chuyên sâu", {"kind": "service"}, "service:501"),
    ("Máy ảnh thuê", {"kind": "rental"}, "product:502"),
    ("Tư vấn ảnh", {"kind": "service"}, "product:503"),
])
def test_search_finds_late_identity_before_limit(catalog, query, options, expected):
    db, _ = catalog
    assert refs(search_current_offerings(db, 1, query, limit=1, **options)) == [expected]


def test_combined_filters_before_limit_and_no_fitment_from_name(catalog):
    db, _ = catalog
    constraints = {"required_attributes": {"màu": "red", "size": "M", "vehicle model": "Vision", "vehicle_year": 2023}}
    assert refs(search_current_offerings(db, 1, "máy ảnh dưới 200k", limit=1, kind="goods", hard_filters=constraints)) == ["product:501"]
    assert search_current_offerings(db, 1, "Vision 2023", hard_filters={"required_attributes": {"vehicle_year": 2024}}) == []
    # The name still says Vision 2023, but absent authoritative attributes are unknown.
    db.get(Product, 501).metadata_ = {"offering_type": "goods"}
    db.flush()
    assert search_current_offerings(db, 1, "Vision 2023", hard_filters=constraints) == []


def test_query_attribute_extraction_and_inclusive_budget(catalog):
    db, _ = catalog
    assert refs(search_current_offerings(db, 1, "máy ảnh màu đỏ size M dưới 120k", limit=1)) == ["product:501"]
    assert search_current_offerings(db, 1, "SKU LATE-501", budget=119999) == []
    assert refs(search_current_offerings(db, 1, "SKU LATE-501", budget=Decimal("120000"))) == ["product:501"]


def test_attributes_do_not_erase_product_words(catalog):
    db, _ = catalog
    assert search_current_offerings(db, 1, "áo khoác màu đỏ size M") == []


def test_nested_attributes_override_conflicting_legacy_metadata(catalog):
    db, _ = catalog
    db.get(Product, 501).metadata_ = {"vehicle_year": 2023, "attributes": {"vehicle_year": 2024}}
    db.flush()
    assert search_current_offerings(db, 1, "SKU LATE-501", hard_filters={"required_attributes": {"vehicle_year": 2023}}) == []
    assert refs(search_current_offerings(db, 1, "SKU LATE-501", hard_filters={"required_attributes": {"vehicle_year": 2024}})) == ["product:501"]


def test_sku_exact_not_prefix_and_parameterized(catalog):
    db, _ = catalog
    assert search_current_offerings(db, 1, "SKU LATE-50") == []
    assert search_current_offerings(db, 1, "", hard_filters={"sku": "LATE-501' OR 1=1 --"}) == []
    assert refs(search_current_offerings(db, 2, "", hard_filters={"sku": "late-501"})) == ["product:601"]


def test_exact_sku_ranks_above_another_products_name(catalog):
    db, _ = catalog
    db.get(Product, 1).name = "LATE-501"
    db.flush()
    assert refs(search_current_offerings(db, 1, "Mua LATE-501", limit=1)) == ["product:501"]


def test_tenant_active_total_limit_and_pagination(catalog):
    db, _ = catalog
    first = current_offerings(db, 1)
    assert len(first) == 12
    assert refs(first) == [f"product:{i}" for i in range(1, 13)]
    second = current_offerings(db, 1, None, limit=12, offset=12)
    assert len(second) == 12 and not set(refs(first)) & set(refs(second))
    page = search_current_offerings(db, 1, "", limit=100, offset=125)
    assert len(page) == 100  # One shared limit, not 100 per source.
    assert "service:1" in refs(page)
    assert not set(refs(page)) & {"product:601", "product:602", "service:601", "service:602"}
    assert {"ref", "name", "sku", "kind", "price", "billing_unit", "available", "availability_basis", "description"} <= first[0].keys()


@pytest.mark.parametrize("ref,kind", [("product:501", "goods"), ("product:502", "rental"), ("product:503", "service"), ("service:501", "service")])
def test_exact_ref_independent_of_page_budget_and_current_stock(catalog, ref, kind):
    db, _ = catalog
    assert ref not in refs(search_current_offerings(db, 1, "", limit=1, budget=1))
    item = get_current_offering(db, 1, ref)
    assert item["ref"] == ref and item["kind"] == kind
    if ref == "product:501":
        assert item["available"] == 7
        # Bypass the identity map to prove exact lookup refreshes live values.
        db.execute(update(Product).where(Product.id == 501).values(price=130000, stock_quantity=0).execution_options(synchronize_session=False))
        refreshed = get_current_offering(db, 1, ref)
        assert refreshed["price"] == "130000.00" and refreshed["available"] == 0
    if kind == "service":
        assert item["available"] is None
    if kind == "rental":
        assert "date-specific" in item["availability_basis"]


@pytest.mark.parametrize("ref", [None, "product:0", "product:-1", "product:01", "product:1 OR 1=1", "product:2147483648", "rental:502", "service:602", "product:602", "product:601", "service:601", "product:999999"])
def test_invalid_foreign_or_inactive_refs_fail_closed(catalog, ref):
    assert get_current_offering(catalog[0], 1, ref) is None


def test_appointment_module_and_duration_filter(catalog):
    db, _ = catalog
    assert refs(search_current_offerings(db, 1, "", limit=1, hard_filters={"object_type": "service", "required_attributes": {"duration": "90 minutes"}})) == ["service:501"]
    assert refs(search_current_offerings(db, 1, "duration: 90 minutes, dịch vụ", kind="service")) == ["service:501"]
    save_workspace_config(db, 1, {
        "business_type": "retail",
        "enabled_modules": ["retail"],
        "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS"],
    })
    db.commit()
    assert get_current_offering(db, 1, "service:501") is None
    assert search_current_offerings(db, 1, "", hard_filters={"object_type": "service"}) == []
    assert refs(search_current_offerings(db, 1, "", kind="service")) == ["product:503"]


def test_kind_default_and_object_type_are_distinct(catalog):
    db, _ = catalog
    db.get(Product, 501).metadata_ = {"offering_type": "invalid"}
    db.flush()
    profile = BusinessProfile(default_offering_type="rental")
    assert get_current_offering(db, 1, "product:501", profile)["kind"] == "rental"
    assert refs(search_current_offerings(db, 1, "SKU LATE-501", kind="rental", profile=profile)) == ["product:501"]
    assert search_current_offerings(db, 1, "SKU LATE-501", kind="goods", profile=profile) == []
    assert refs(search_current_offerings(db, 1, "", kind="service", hard_filters={"object_type": "product"})) == ["product:503"]


@pytest.mark.parametrize("options", [{"limit": 0}, {"limit": 101}, {"limit": True}, {"offset": -1}, {"kind": "product"}, {"budget": "NaN"}, {"budget": -1}, {"hard_filters": {"business_id": 2}}, {"hard_filters": {"required_attributes": {"size": []}}}])
def test_invalid_filters_are_rejected(catalog, options):
    with pytest.raises(ValueError):
        search_current_offerings(catalog[0], 1, "", **options)


def test_postgresql_sql_keeps_filters_before_limit_without_executing_postgres(catalog):
    db, _ = catalog
    statements = []
    def capture(state):
        if state.is_select:
            statements.append(state.statement)
    event.listen(db, "do_orm_execute", capture)
    try:
        search_current_offerings(db, 1, "", limit=1, kind="goods", budget=120000,
                                 hard_filters={"sku": "LATE-501", "required_attributes": {"color": "red"}})
    finally:
        event.remove(db, "do_orm_execute", capture)
    statement = next(s for s in statements if "rank" in s.selected_columns.keys())
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    before_limit = sql.split("LIMIT")[0]
    assert all(token in before_limit for token in ("business_id", "status", "sku", "price", "EXISTS", "ORDER BY"))
    assert "offering_type" in str(compiled.params)
    assert "LATE-501" not in sql and "120000" not in sql  # Bound values.


def test_native_postgresql_json_sql_is_compiled_without_database_connection(catalog):
    db, _ = catalog
    dialect_db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=postgresql.dialect()), query=db.query, execute=db.execute)
    class Captured(Exception):
        pass
    statements = []
    def capture(state):
        if state.is_select and "rank" in state.statement.selected_columns.keys():
            statements.append(state.statement)
            raise Captured()
    event.listen(db, "do_orm_execute", capture)
    try:
        with pytest.raises(Captured):
            search_current_offerings(dialect_db, 1, "", profile=BusinessProfile(), hard_filters={"required_attributes": {"vehicle_year": 2023}})
    finally:
        event.remove(db, "do_orm_execute", capture)
    sql = str(statements[0].compile(dialect=postgresql.dialect()))
    assert "jsonb_array_elements_text" in sql and "jsonb_build_array" in sql
    assert "json_each" not in sql and "business_id" in sql


@pytest.mark.parametrize("value", [True, [True, False]])
def test_boolean_attributes_are_not_confused_with_numeric_values(catalog, value):
    db, _ = catalog
    db.get(Product, 501).metadata_ = {"attributes": {"waterproof": value}}
    db.get(Product, 502).metadata_ = {"attributes": {"waterproof": 1}}
    db.flush()
    assert refs(search_current_offerings(db, 1, "", hard_filters={"required_attributes": {"waterproof": True}})) == ["product:501"]


def workflow_turn(db, conversation, ref, text, fields=None, action="collect"):
    payload = {"action": action, "action_evidence": text, "offering_ref": ref, "fields": fields or {}}
    with patch("app.services.business_request.call_llm", return_value=json.dumps(payload)) as llm, \
         patch("app.services.business_request.record_quota_usage") as quota:
        result = advance_business_request(db, business_id=1, conversation=conversation, query=text, history=[], job_key=text)
    quota.assert_called_once()
    prompt = json.loads(llm.call_args.args[0][-1]["content"])
    assert len(prompt["catalog"]) <= 12
    return result, prompt


@pytest.mark.parametrize("ref,kind", [("product:501", "goods"), ("product:502", "rental"), ("product:503", "service"), ("service:501", "service")])
def test_late_workflow_ref_collect_review_submit_with_bounded_prompt(catalog, ref, kind):
    db, conversation = catalog
    fields = {"name": {"value": "Khách Thử", "evidence": "Khách Thử"},
              "phone": {"value": "0901234567", "evidence": "0901234567"},
              "payment_method": {"value": "cash", "evidence": "tiền mặt"}}
    if kind == "goods":
        fields["quantity"] = {"value": "2", "evidence": "2"}
    elif kind == "rental":
        fields["start_date"] = {"value": "2099-11-01", "evidence": "01/11/2099"}
    else:
        fields["starts_at"] = {"value": "2099-11-01T09:00:00+07:00", "evidence": "01/11/2099 09:00"}
    text = "Khách Thử 0901234567, 2, 01/11/2099 09:00, tiền mặt"
    result, _ = workflow_turn(db, conversation, ref, text, fields)
    assert result["state"] == "review" and not result["order_created"]
    assert db.query(Order).count() == 0
    # Approval contains no catalog words; pending exact reference must remain.
    result, prompt = workflow_turn(db, conversation, None, "Xác nhận gửi yêu cầu", action="submit")
    assert ref in refs(prompt["catalog"])
    assert result["state"] == "submitted" and result["order_created"]
    order = db.query(Order).one()
    assert order.total_amount == (240000 if kind == "goods" else 150000 if kind == "rental" else 80000 if ref.startswith("product:") else 180000)
    if kind != "service":
        assert db.query(OrderItem).one().product_id == int(ref.split(":")[1])
    if ref.startswith("service:"):
        assert db.query(Appointment).one().service_id == 501
    assert db.query(CustomerCollectionSession).one().status == "completed"


def test_workflow_rechecks_active_after_row_lock(catalog):
    db, conversation = catalog
    original = get_current_offering
    calls = []
    def invalidate_after_first_lookup(*args, **kwargs):
        item = original(*args, **kwargs)
        if args[2] == "product:501":
            calls.append(args[2])
            if len(calls) == 1:
                db.execute(update(Product).where(Product.id == 501).values(status="inactive"))
        return item
    with patch("app.services.business_request.get_current_offering", side_effect=invalidate_after_first_lookup):
        result, _ = workflow_turn(db, conversation, "product:501", "Tôi muốn đặt hàng")
    assert len(calls) == 2 and result["state"] == "unavailable"
    assert db.query(Order).count() == 0 and db.query(CustomerCollectionSession).count() == 0
