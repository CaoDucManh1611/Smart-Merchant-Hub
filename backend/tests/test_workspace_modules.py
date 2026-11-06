import pytest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.appointments import AppointmentUpdate, _validate_disabled_appointment_update, update_appointment
from app.database.bases import TenantBase
from app.models.business_setting import BusinessSetting
from app.tenancy.context import TenantContext
from app.tenancy.workspace_modules import (
    get_workspace_config,
    require_module_enabled,
    save_workspace_config,
)


def _request(method: str, path: str) -> Request:
    return Request({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"", "headers": [], "client": ("test", 1), "server": ("test", 80),
    })


def test_new_shop_starts_with_core_only_and_configs_are_tenant_scoped():
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            default = get_workspace_config(db, 7)
            assert default["business_model"] == "RETAIL"
            assert default["industry_ids"] == []
            assert default["enabled_modules"] == []
            assert default["enabled_capabilities"] == ["CORE_CRM"]
            assert default["explicitly_enabled_capabilities"] == []

            save_workspace_config(db, 7, {
                "business_model": "APPOINTMENT_SERVICE",
                "industry_ids": ["beauty_cosmetics", "services_repair"],
                "enabled_capabilities": ["CORE_CRM", "APPOINTMENT_TOOLS", "CUSTOMER_TOOLS", "PROJECT_QUOTATION_TOOLS"],
                "purchase_model_reference_industry": "services",
            })
            db.commit()
            saved = get_workspace_config(db, 7)
            assert saved["business_model"] == "APPOINTMENT_SERVICE"
            assert saved["business_type"] == "services"
            assert saved["industry_ids"] == ["beauty_cosmetics", "services_repair"]
            assert set(saved["enabled_capabilities"]) == {
                "CORE_CRM", "APPOINTMENT_TOOLS", "CUSTOMER_TOOLS", "PROJECT_QUOTATION_TOOLS",
            }
            assert saved["purchase_model_reference_industry"] == "services"
            assert get_workspace_config(db, 8)["enabled_capabilities"] == ["CORE_CRM"]

            # Changing only the business model must preserve industry, grants,
            # reference mapping and all tenant data.
            save_workspace_config(db, 7, {"business_model": "MULTI_SERVICE"})
            db.commit()
            changed = get_workspace_config(db, 7)
            assert changed["business_model"] == "MULTI_SERVICE"
            assert changed["industry_ids"] == saved["industry_ids"]
            assert changed["enabled_capabilities"] == saved["enabled_capabilities"]
            assert changed["purchase_model_reference_industry"] == "services"
            assert changed["config_version"] == saved["config_version"] + 1
    finally:
        engine.dispose()


def test_legacy_module_config_is_preserved_as_existing_grants():
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            config = save_workspace_config(db, 3, {
                "business_type": "retail",
                "enabled_modules": ["retail"],
                "legacy_module_update": True,
            })
            db.commit()
            assert config["capability_source"] == "legacy_workspace_modules"
            assert {"RETAIL_TOOLS", "INVENTORY_TOOLS", "ORDER_TOOLS"}.issubset(
                config["enabled_capabilities"]
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("caps", [
    ["CORE_CRM", "ORDER_TOOLS"],
    ["CORE_CRM", "INVENTORY_TOOLS"],
    ["CORE_CRM", "RECOMMENDATION_TOOLS"],
])
def test_dependent_capability_cannot_be_enabled_without_retail(caps):
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            with pytest.raises(ValueError, match="phụ thuộc"):
                save_workspace_config(db, 7, {
                    "business_model": "MULTI_SERVICE",
                    "enabled_capabilities": caps,
                })
            db.rollback()
            assert get_workspace_config(db, 7)["enabled_capabilities"] == ["CORE_CRM"]
    finally:
        engine.dispose()


def test_unknown_or_duplicate_industry_config_fails_closed():
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            with pytest.raises(ValueError, match="Industry Profile"):
                save_workspace_config(db, 7, {
                    "business_model": "RETAIL", "industry_ids": ["not-a-real-industry"],
                    "enabled_capabilities": ["CORE_CRM"],
                })
            with pytest.raises(ValueError, match="Industry Profile"):
                save_workspace_config(db, 7, {
                    "business_model": "RETAIL", "industry_ids": ["fashion_apparel", "fashion_apparel"],
                    "enabled_capabilities": ["CORE_CRM"],
                })
    finally:
        engine.dispose()


def test_backend_permission_guard_fails_closed_but_preserves_read_only_history():
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            save_workspace_config(db, 7, {"business_model": "RETAIL", "enabled_capabilities": ["CORE_CRM"]})
            db.commit()
            tenant = TenantContext(business_id=7, source="test")

            with pytest.raises(HTTPException) as disabled_catalog:
                require_module_enabled("retail")(
                    request=_request("GET", "/api/products"), db=db, tenant=tenant,
                )
            assert disabled_catalog.value.status_code == 403

            with pytest.raises(HTTPException) as disabled_order:
                require_module_enabled("retail")(
                    request=_request("POST", "/api/sales/orders"), db=db, tenant=tenant,
                )
            assert disabled_order.value.status_code == 403

            # History can still be inspected after the shop turns off the tools.
            require_module_enabled("retail")(
                request=_request("GET", "/api/sales/orders"), db=db, tenant=tenant,
            )

            save_workspace_config(db, 7, {
                "business_model": "MULTI_SERVICE",
                "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS", "ORDER_TOOLS"],
            })
            db.commit()
            require_module_enabled("retail")(
                request=_request("POST", "/api/sales/orders"), db=db, tenant=tenant,
            )
    finally:
        engine.dispose()


def test_disabling_appointment_capability_allows_safe_existing_edit_only():
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            save_workspace_config(db, 7, {"business_model": "APPOINTMENT_SERVICE", "enabled_capabilities": ["CORE_CRM"]})
            db.commit()
            guard = require_module_enabled("appointments")
            tenant = TenantContext(business_id=7, source="test")
            guard(request=_request("PATCH", "/api/appointments/12"), db=db, tenant=tenant)
            with pytest.raises(HTTPException) as disabled_recommendations:
                require_module_enabled("recommendations")(
                    request=_request("POST", "/api/recommendations"), db=db, tenant=tenant,
                )
            assert disabled_recommendations.value.status_code == 403
            with pytest.raises(HTTPException) as transition:
                guard(request=_request("POST", "/api/appointments/12/confirm"), db=db, tenant=tenant)
            assert transition.value.status_code == 403
    finally:
        engine.dispose()


def test_payment_configuration_is_checked_per_tenant_and_fails_closed_until_complete():
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            config = get_workspace_config(db, 7)
            assert "payment_configuration" not in config["available_dependencies"]
            with pytest.raises(ValueError, match="payment_configuration"):
                save_workspace_config(db, 7, {
                    "business_model": "RETAIL",
                    "enabled_capabilities": ["CORE_CRM", "PAYMENT_TOOLS"],
                })
            db.rollback()

            db.add_all([
                BusinessSetting(business_id=7, key="shop.bank_transfer.enabled", value="true"),
                BusinessSetting(business_id=7, key="shop.bank_transfer.bank_bin", value="970415"),
                BusinessSetting(business_id=7, key="shop.bank_transfer.account_number_encrypted", value="valid-ciphertext"),
                BusinessSetting(business_id=7, key="shop.bank_transfer.account_name", value="SHOP OWNER"),
            ])
            db.commit()
            with patch("app.services.channel_credentials.decrypt_token", return_value="12345678"):
                ready = save_workspace_config(db, 7, {
                    "business_model": "RETAIL",
                    "enabled_capabilities": ["CORE_CRM", "PAYMENT_TOOLS"],
                })
            assert "payment_configuration" in ready["available_dependencies"]
            payment = next(item for item in ready["capabilities"] if item["capability_id"] == "PAYMENT_TOOLS")
            assert payment["dependency_status"] == "integration_available_shop_data_unchecked"
            assert "payment_configuration" not in payment["missing_dependencies"]

            with patch("app.services.channel_credentials.decrypt_token", side_effect=ValueError("invalid ciphertext")):
                corrupted = get_workspace_config(db, 7)
            assert "payment_configuration" not in corrupted["available_dependencies"]

            other = get_workspace_config(db, 8)
            assert "payment_configuration" not in other["available_dependencies"]
    finally:
        engine.dispose()


@pytest.mark.parametrize("changes", [
    {"status": "confirmed"},
    {"status": "completed"},
    {"starts_at": "2026-11-05T09:00:00"},
    {"customer_id": 88},
    {"service_id": 14},
    {"assigned_user_id": 3},
    {"reminder_minutes_before": 0},
    {"send_customer_reminder": True},
])
def test_disabled_appointment_capability_rejects_workflow_and_schedule_mutations(changes):
    with pytest.raises(HTTPException) as rejected:
        _validate_disabled_appointment_update({"enabled_capabilities": ["CORE_CRM"]}, changes)
    assert rejected.value.status_code == 403
    assert rejected.value.detail["code"] == "workspace_capability_disabled"


def test_disabled_appointment_capability_allows_notes_only_and_enabled_capability_allows_updates():
    _validate_disabled_appointment_update({"enabled_capabilities": ["CORE_CRM"]}, {"notes": "Internal note"})
    _validate_disabled_appointment_update({"enabled_capabilities": ["CORE_CRM"]}, {})
    _validate_disabled_appointment_update(
        {"enabled_capabilities": ["CORE_CRM", "APPOINTMENT_TOOLS"]},
        {"status": "confirmed", "starts_at": "2026-11-05T09:00:00"},
    )


def test_disabled_appointment_patch_blocks_status_before_linked_payment_or_schedule_reads():
    db = Mock()
    with patch(
        "app.tenancy.workspace_modules.get_workspace_config",
        return_value={"enabled_capabilities": ["CORE_CRM"]},
    ), pytest.raises(HTTPException) as rejected:
        update_appointment(
            appointment_id=12,
            payload=AppointmentUpdate(status="confirmed"),
            db=db,
            user_db=Mock(),
            tenant=TenantContext(business_id=7, source="test"),
            platform_db=Mock(),
        )
    assert rejected.value.status_code == 403
    db.query.assert_not_called()


def test_disabled_appointment_notes_patch_does_not_requeue_reminder_job():
    db = Mock()
    row = SimpleNamespace(
        id=12, business_id=7, status="scheduled", notes=None,
        customer_id=21, service_id=4, assigned_user_id=None,
        starts_at=None, ends_at=None, reminder_minutes_before=30,
        send_customer_reminder=False, reminder_at=None, reminder_sent_at=None,
        updated_at=None,
    )
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = row
    with patch(
        "app.tenancy.workspace_modules.get_workspace_config",
        return_value={"enabled_capabilities": ["CORE_CRM"]},
    ), patch("app.api.appointments._linked_payment_order", return_value=None), \
         patch("app.api.appointments._ensure_no_conflict"), \
         patch("app.api.appointments._enqueue_reminder") as enqueue, \
         patch("app.api.appointments._appointment_out", return_value={"id": row.id}):
        result = update_appointment(
            appointment_id=12,
            payload=AppointmentUpdate(notes="Internal note"),
            db=db,
            user_db=Mock(),
            tenant=TenantContext(business_id=7, source="test"),
            platform_db=Mock(),
        )

    assert result == {"id": 12}
    assert row.notes == "Internal note"
    enqueue.assert_not_called()
