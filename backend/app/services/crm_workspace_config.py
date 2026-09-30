"""Read and validate shop-owned CRM customization."""

from __future__ import annotations

import math
from datetime import date

from sqlalchemy.orm import Session

from app.models.crm_workspace_config import CrmWorkspaceConfig


DEFAULT_PIPELINE_STAGES = [
    {"key": "new", "label": "Mới"},
    {"key": "qualified", "label": "Đã xác định nhu cầu"},
    {"key": "proposal", "label": "Đã gửi đề xuất"},
    {"key": "won", "label": "Đã chốt"},
    {"key": "lost", "label": "Không thành công"},
]


def get_crm_workspace_config(db: Session, business_id: int) -> dict:
    row = db.query(CrmWorkspaceConfig).filter(CrmWorkspaceConfig.business_id == business_id).first()
    return {
        "customer_fields": row.customer_fields if row and isinstance(row.customer_fields, list) else [],
        "pipeline_stages": row.pipeline_stages if row and isinstance(row.pipeline_stages, list) else DEFAULT_PIPELINE_STAGES,
    }


def validate_customer_custom_fields(values: dict, definitions: list[dict]) -> dict:
    if not isinstance(values, dict):
        raise ValueError("Giá trị trường tùy chỉnh phải là một đối tượng.")
    by_key = {str(field["key"]): field for field in definitions}
    unknown = set(values) - set(by_key)
    if unknown:
        raise ValueError(f"Trường chưa được cấu hình: {', '.join(sorted(unknown))}.")

    normalized = {}
    for key, value in values.items():
        if value is None or value == "":
            normalized[key] = None
            continue
        definition = by_key[key]
        kind = definition["type"]
        if kind == "text":
            if not isinstance(value, str) or len(value) > 2000:
                raise ValueError(f"{definition['label']} phải là văn bản tối đa 2.000 ký tự.")
        elif kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{definition['label']} phải là số hợp lệ.")
        elif kind == "date":
            try:
                date.fromisoformat(value) if isinstance(value, str) else None
            except ValueError as exc:
                raise ValueError(f"{definition['label']} cần đúng định dạng ngày.") from exc
            if not isinstance(value, str):
                raise ValueError(f"{definition['label']} cần đúng định dạng ngày.")
        elif kind == "select" and value not in definition.get("options", []):
            raise ValueError(f"{definition['label']} không nằm trong danh sách lựa chọn.")
        elif kind == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{definition['label']} phải là đúng hoặc sai.")
        normalized[key] = value
    return normalized
