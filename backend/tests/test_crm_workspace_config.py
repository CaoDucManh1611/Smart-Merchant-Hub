import pytest
from pydantic import ValidationError

from app.schemas.crm_config import CrmWorkspaceConfigUpdate
from app.services.crm_workspace_config import validate_customer_custom_fields


def test_shop_pipeline_keeps_system_stages_and_accepts_custom_stage():
    config = CrmWorkspaceConfigUpdate.model_validate({
        "customer_fields": [],
        "pipeline_stages": [
            {"key": "new", "label": "Mới"},
            {"key": "qualified", "label": "Đang tư vấn"},
            {"key": "won", "label": "Thành công"},
            {"key": "lost", "label": "Không thành công"},
            {"key": "renewal", "label": "Gia hạn"},
        ],
    })
    assert config.pipeline_stages[-1].key == "renewal"


def test_shop_pipeline_rejects_removing_terminal_stages():
    with pytest.raises(ValidationError):
        CrmWorkspaceConfigUpdate.model_validate({
            "customer_fields": [],
            "pipeline_stages": [
                {"key": "new", "label": "Mới"},
                {"key": "won", "label": "Đã chốt"},
                {"key": "custom", "label": "Đang làm"},
            ],
        })


def test_customer_fields_are_validated_against_shop_schema():
    schema = [
        {"key": "customer_type", "label": "Loại khách", "type": "select", "options": ["Mới", "VIP"]},
        {"key": "budget", "label": "Ngân sách", "type": "number", "options": []},
    ]
    assert validate_customer_custom_fields({"customer_type": "VIP", "budget": 0}, schema) == {
        "customer_type": "VIP", "budget": 0,
    }
    with pytest.raises(ValueError):
        validate_customer_custom_fields({"customer_type": "Unknown"}, schema)
