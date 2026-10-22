"""Shop-owned bank transfer details and order-specific VietQR links."""

from __future__ import annotations

from binascii import crc_hqx
import re
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.business_setting import BusinessSetting
from app.services.channel_credentials import decrypt_token, encrypt_token
from app.services.vietnam_banks import BANKS
from app.services.vietqr_payment_service import qr_content


PREFIX = "shop.bank_transfer."
FIELDS = ("enabled", "bank_bin", "account_number_encrypted", "account_name")


class BankTransferSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    bank_bin: str = Field(default="", max_length=6)
    account_number: str = Field(default="", max_length=34)
    account_name: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def validate_fields(self):
        for field in ("bank_bin", "account_number", "account_name"):
            value = getattr(self, field).strip()
            if any(ord(char) < 32 for char in value):
                raise ValueError("Thông tin tài khoản không hợp lệ.")
            setattr(self, field, value)
        if self.bank_bin and self.bank_bin not in BANKS:
            raise ValueError("Ngân hàng chưa được hỗ trợ tạo VietQR.")
        if self.account_number and (
            not self.account_number.isascii()
            or not self.account_number.isdigit()
            or not 6 <= len(self.account_number) <= 34
        ):
            raise ValueError("Số tài khoản phải có từ 6 đến 34 chữ số.")
        if self.enabled and not all((self.bank_bin, self.account_number, self.account_name)):
            raise ValueError("Cần nhập ngân hàng, số tài khoản và tên chủ tài khoản.")
        return self


def _values(db: Session, business_id: int) -> dict[str, str]:
    rows = db.scalars(
        select(BusinessSetting).where(
            BusinessSetting.business_id == int(business_id),
            BusinessSetting.key.in_([PREFIX + field for field in FIELDS]),
        )
    ).all()
    return {row.key.removeprefix(PREFIX): row.value for row in rows}


def read_shop_bank_transfer(db: Session, business_id: int) -> dict[str, object]:
    values = _values(db, business_id)
    bank_bin = values.get("bank_bin", "")
    encrypted_account_number = values.get("account_number_encrypted", "")
    account_number = decrypt_token(encrypted_account_number, settings.CHANNEL_ENCRYPTION_KEY) if encrypted_account_number else ""
    return {
        "enabled": values.get("enabled") == "true",
        "bank_bin": bank_bin,
        "account_number": account_number,
        "account_name": values.get("account_name", ""),
        "bank_name": BANKS.get(bank_bin, ""),
        "bank_options": [{"bin": code, "name": name} for code, name in BANKS.items()],
    }


def save_shop_bank_transfer(
    db: Session,
    business_id: int,
    payload: BankTransferSettingsUpdate,
) -> dict[str, object]:
    payload_values = payload.model_dump()
    values = {
        "enabled": "true" if payload_values["enabled"] else "false",
        "bank_bin": payload_values["bank_bin"],
        "account_number_encrypted": encrypt_token(
            payload_values["account_number"], settings.CHANNEL_ENCRYPTION_KEY
        ) if payload_values["account_number"] else "",
        "account_name": payload_values["account_name"],
    }
    for field, stored_value in values.items():
        setting_key = PREFIX + field
        row = db.scalar(
            select(BusinessSetting).where(
                BusinessSetting.business_id == int(business_id),
                BusinessSetting.key == setting_key,
            )
        )
        if row is None:
            db.add(BusinessSetting(business_id=int(business_id), key=setting_key, value=stored_value))
        else:
            row.value = stored_value
    db.flush()
    return read_shop_bank_transfer(db, business_id)


def _parse_tlv(data: str) -> dict[str, str]:
    fields = {}
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data) or not data[offset + 2:offset + 4].isdigit():
            raise ValueError("Mã QR không đúng cấu trúc VietQR.")
        tag, length = data[offset:offset + 2], int(data[offset + 2:offset + 4])
        start, end = offset + 4, offset + 4 + length
        if end > len(data):
            raise ValueError("Mã QR bị thiếu dữ liệu.")
        fields[tag] = data[start:end]
        offset = end
    return fields


def validate_shop_bank_transfer(payload: BankTransferSettingsUpdate) -> dict[str, object]:
    """Validate account formatting and round-trip a local VietQR fixture."""
    if not all((payload.bank_bin, payload.account_number, payload.account_name)):
        raise ValueError("Cần nhập ngân hàng, số tài khoản và tên chủ tài khoản.")
    config = BankTransferSettingsUpdate(
        enabled=True,
        bank_bin=payload.bank_bin,
        account_number=payload.account_number,
        account_name=payload.account_name,
    )
    amount, reference = 1000, "SMHCHECK"
    qr = qr_content(config.bank_bin, config.account_number, amount, reference)
    if qr[-8:-4] != "6304" or f"{crc_hqx(qr[:-4].encode('ascii'), 0xffff):04X}" != qr[-4:]:
        raise ValueError("Không kiểm tra được mã kiểm tra VietQR.")
    fields = _parse_tlv(qr[:-8])
    merchant = _parse_tlv(fields.get("38", ""))
    recipient = _parse_tlv(merchant.get("01", ""))
    additional = _parse_tlv(fields.get("62", ""))
    if not (
        recipient.get("00") == config.bank_bin
        and recipient.get("01") == config.account_number
        and fields.get("53") == "704"
        and fields.get("54") == str(amount)
        and fields.get("58") == "VN"
        and additional.get("08") == reference
    ):
        raise ValueError("Ngân hàng, số tài khoản hoặc nội dung trong QR không khớp cấu hình.")
    return {
        "status": "format_and_qr_valid",
        "format_valid": True,
        "qr_validated": True,
        "beneficiary_verified": False,
        "bank_name": BANKS[config.bank_bin],
        "account_last4": config.account_number[-4:],
        "message": "Định dạng và QR khớp cấu hình. Chưa xác minh tên chủ tài khoản với ngân hàng.",
    }


def order_qr_url(
    *, bank_bin: str, account_number: str, account_name: str, amount: int, reference: str
) -> str:
    """Use VietQR's documented Quick Link to render this order's transfer QR."""
    safe_reference = re.sub(r"[^A-Za-z0-9]", "", str(reference or ""))[:25] or "THANHTOAN"
    query = urlencode({
        "amount": max(0, int(amount)),
        "addInfo": safe_reference,
        "accountName": account_name,
    })
    return f"https://img.vietqr.io/image/{bank_bin}-{account_number}-compact2.png?{query}"


def order_transfer_instructions(
    db: Session,
    *,
    business_id: int,
    order_number: str,
    amount: int,
    language: str = "vi",
) -> str:
    config = read_shop_bank_transfer(db, business_id)
    if not config["enabled"]:
        return (
            "Shop chưa cài thông tin nhận chuyển khoản. Nhân viên sẽ gửi hướng dẫn thanh toán cho bạn."
            if language != "en"
            else "The shop has not set up bank transfer details yet. A staff member will send payment instructions."
        )

    reference = re.sub(r"[^A-Za-z0-9]", "", str(order_number or ""))[:25] or "THANHTOAN"
    qr_url = order_qr_url(
        bank_bin=str(config["bank_bin"]),
        account_number=str(config["account_number"]),
        account_name=str(config["account_name"]),
        amount=amount,
        reference=reference,
    )
    if language == "en":
        formatted_amount = f"{amount:,}"
    else:
        formatted_amount = f"{amount:,}".replace(",", ".")

    if language == "en":
        return (
            f"Bank transfer for order {order_number}\n"
            f"Bank: {config['bank_name']}\nAccount holder: {config['account_name']}\n"
            f"Account number: {config['account_number']}\nAmount: {formatted_amount} VND\n"
            f"Transfer note: {reference}\nQR code: {qr_url}\n"
            "The shop will update payment status after verifying the incoming transfer."
        )
    return (
        f"🏦 Thông tin chuyển khoản đơn {order_number}\n"
        f"Ngân hàng: {config['bank_name']}\nChủ tài khoản: {config['account_name']}\n"
        f"Số tài khoản: {config['account_number']}\nSố tiền: {formatted_amount} đồng\n"
        f"Nội dung chuyển khoản: {reference}\nMã QR: {qr_url}\n"
        "Shop sẽ cập nhật thanh toán sau khi xác nhận tiền đã vào tài khoản."
    )
