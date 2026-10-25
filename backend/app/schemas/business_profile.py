"""Shop-owned business rules; no industry name controls runtime behavior."""
from typing import Literal
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError


class ChargeLine(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    label: str=Field(min_length=1,max_length=120)
    amount: Decimal=Field(gt=0,le=9999999999,max_digits=12,decimal_places=0)

class PaymentPolicy(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    mode: Literal["order_total","manual"]="manual"
    label: str=Field(default="Khoản thu theo đơn",min_length=1,max_length=120)
    fixed_charges: list[ChargeLine]=Field(default_factory=list,max_length=12)


class CollectionField(BaseModel):
    model_config=ConfigDict(extra="forbid")
    key: str=Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str=Field(min_length=1,max_length=100)
    type: Literal["text","phone","date","datetime","quantity"]="text"
    future_only: bool=False


def default_fields():
    contact=[{"key":"name","label":"Họ tên","type":"text"},{"key":"phone","label":"Số liên hệ","type":"phone"}]
    return {
        "goods":[*contact,{"key":"quantity","label":"Số lượng","type":"quantity"}],
        "service":[*contact,{"key":"starts_at","label":"Thời gian mong muốn","type":"datetime","future_only":True}],
        "rental":[*contact,{"key":"start_date","label":"Ngày bắt đầu thuê","type":"date","future_only":True}],
    }


class BusinessProfile(BaseModel):
    model_config=ConfigDict(extra="forbid")
    default_offering_type: Literal["goods","service","rental"]="goods"
    default_billing_unit: str | None=Field(default=None,max_length=40)
    payment_policies: dict[str,PaymentPolicy]=Field(default_factory=lambda:{
        "goods":PaymentPolicy(mode="order_total"),"service":PaymentPolicy(mode="order_total"),"rental":PaymentPolicy()})
    payment_methods: list[Literal["cash","bank_transfer","cod"]]=Field(default_factory=lambda:["cash","bank_transfer"],min_length=1,max_length=3)
    timezone: str=Field(default="Asia/Ho_Chi_Minh",max_length=80)
    collection_fields: dict[str,list[CollectionField]]=Field(default_factory=lambda: {
        k:[CollectionField(**v) for v in values] for k,values in default_fields().items()})

    @model_validator(mode="after")
    def validate_fields(self):
        try: ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error: raise ValueError("Múi giờ không hợp lệ") from error
        if set(self.collection_fields)!={"goods","service","rental"}:
            raise ValueError("Cần cấu hình ba loại hàng hóa, dịch vụ và cho thuê")
        if len(set(self.payment_methods))!=len(self.payment_methods):
            raise ValueError("Hình thức thanh toán không được trùng")
        if set(self.payment_policies)!={"goods","service","rental"}:
            raise ValueError("Cần quy định khoản thu cho ba loại cung cấp")
        reserved={"payment_method","product_id","draft_order_id","phone_collected","encrypted_phone","offering_ref","submitted"}
        for fields in self.collection_fields.values():
            if not 1<=len(fields)<=12 or len({f.key for f in fields})!=len(fields):
                raise ValueError("Mỗi loại cần 1–12 trường khác nhau")
            if any(f.key in reserved for f in fields):
                raise ValueError("Tên trường trùng dữ liệu hệ thống")
            if sum(f.type=="phone" for f in fields)>1:
                raise ValueError("Mỗi yêu cầu chỉ có một số liên hệ chính")
            if any(f.type=="quantity" and f.key!="quantity" for f in fields):
                raise ValueError("Trường số lượng cần mã quantity")
        return self
