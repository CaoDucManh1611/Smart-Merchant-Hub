"""Shop-configurable CRM profile fields and pipeline labels."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class CustomerFieldDefinition(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=80)
    type: Literal["text", "number", "date", "select", "boolean"] = "text"
    options: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Tên trường không được để trống.")
        return value

    @field_validator("options")
    @classmethod
    def clean_options(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if any(len(value) > 80 for value in normalized):
            raise ValueError("Mỗi lựa chọn tối đa 80 ký tự.")
        return normalized

    @model_validator(mode="after")
    def validate_options_for_type(self):
        if self.type == "select" and not self.options:
            raise ValueError("Trường dạng danh sách cần ít nhất một lựa chọn.")
        if self.type != "select" and self.options:
            raise ValueError("Chỉ trường dạng danh sách mới có lựa chọn.")
        return self


class PipelineStageDefinition(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,29}$")
    label: str = Field(min_length=1, max_length=60)

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Tên giai đoạn không được để trống.")
        return value


class CrmWorkspaceConfigUpdate(BaseModel):
    customer_fields: list[CustomerFieldDefinition] = Field(default_factory=list, max_length=30)
    pipeline_stages: list[PipelineStageDefinition] = Field(min_length=3, max_length=20)

    @model_validator(mode="after")
    def validate_unique_and_terminal_stages(self):
        field_keys = [field.key for field in self.customer_fields]
        stage_keys = [stage.key for stage in self.pipeline_stages]
        if len(field_keys) != len(set(field_keys)):
            raise ValueError("Mã trường phải là duy nhất.")
        if len(stage_keys) != len(set(stage_keys)):
            raise ValueError("Mã giai đoạn phải là duy nhất.")
        if not {"new", "won", "lost"}.issubset(stage_keys):
            raise ValueError("Pipeline cần giữ các giai đoạn hệ thống: new, won và lost.")
        return self


class CustomerCustomFieldsUpdate(BaseModel):
    values: dict = Field(default_factory=dict, max_length=30)
