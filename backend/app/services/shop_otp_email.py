"""Tenant-owned SMTP identity for team-invitation OTP email."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.business_setting import BusinessSetting
from app.services.channel_credentials import decrypt_token, encrypt_token
from app.services.otp_delivery import OtpDeliveryNotConfigured, OtpSmtpConfig


_PREFIX = "otp.smtp."
_FIELDS = ("enabled", "host", "port", "security", "username", "password_encrypted", "from_email", "from_name")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _values(db: Session, business_id: int) -> dict[str, str]:
    rows = db.scalars(
        select(BusinessSetting).where(
            BusinessSetting.business_id == int(business_id),
            BusinessSetting.key.in_([_PREFIX + field for field in _FIELDS]),
        )
    ).all()
    return {row.key.removeprefix(_PREFIX): row.value for row in rows}


def read_shop_otp_email(db: Session, business_id: int) -> dict[str, object]:
    values = _values(db, business_id)
    return {
        "enabled": values.get("enabled") == "true",
        "host": values.get("host", "smtp.gmail.com"),
        "port": int(values.get("port", "587")),
        "security": values.get("security", "starttls"),
        "username": values.get("username", ""),
        "from_email": values.get("from_email", ""),
        "from_name": values.get("from_name", ""),
        "password_configured": bool(values.get("password_encrypted")),
    }


def get_shop_otp_smtp_config(db: Session, business_id: int) -> OtpSmtpConfig | None:
    values = _values(db, business_id)
    if values.get("enabled") != "true":
        return None
    try:
        password = decrypt_token(values["password_encrypted"], settings.CHANNEL_ENCRYPTION_KEY)
        config = OtpSmtpConfig(
            host=values["host"],
            port=int(values["port"]),
            username=values["username"],
            password=password,
            from_email=values["from_email"],
            from_name=values.get("from_name", ""),
            security=values.get("security", "starttls"),
        )
    except Exception as error:
        raise OtpDeliveryNotConfigured("Cấu hình SMTP OTP của shop chưa đầy đủ hoặc không giải mã được.") from error
    if not config.host or not config.username or not config.password or not config.from_email:
        raise OtpDeliveryNotConfigured("Cấu hình SMTP OTP của shop chưa đầy đủ.")
    return config


def save_shop_otp_email(db: Session, business_id: int, payload: dict[str, object]) -> dict[str, object]:
    if not payload.get("enabled"):
        rows = db.scalars(
            select(BusinessSetting).where(
                BusinessSetting.business_id == int(business_id),
                BusinessSetting.key.in_([_PREFIX + field for field in _FIELDS]),
            )
        ).all()
        for row in rows:
            db.delete(row)
        db.flush()
        return read_shop_otp_email(db, business_id)

    host = str(payload.get("host") or "").strip().lower().rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError("Máy chủ SMTP không hợp lệ.") from error
    username = str(payload.get("username") or "").strip()
    from_email = str(payload.get("from_email") or "").strip().lower()
    from_name = str(payload.get("from_name") or "").strip()
    port = int(payload.get("port") or 587)
    security = str(payload.get("security") or "starttls").strip().lower()
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host):
        raise ValueError("Nhập tên máy chủ SMTP dạng tên miền, ví dụ smtp.example.com.")
    if (security, port) not in {("starttls", 587), ("ssl", 465)}:
        raise ValueError("Chọn STARTTLS cổng 587 hoặc SSL/TLS cổng 465.")
    if not username or len(username) > 255 or "\r" in username or "\n" in username:
        raise ValueError("Nhập tài khoản SMTP hợp lệ.")
    if not _EMAIL_RE.fullmatch(from_email):
        raise ValueError("Email gửi không hợp lệ.")
    if not from_name or len(from_name) > 120 or "\r" in from_name or "\n" in from_name:
        raise ValueError("Tên người gửi cần từ 1 đến 120 ký tự.")

    existing = _values(db, business_id)
    password = str(payload.get("password") or "")
    if password:
        if len(password) > 200:
            raise ValueError("Mật khẩu ứng dụng SMTP tối đa 200 ký tự.")
        encrypted_password = encrypt_token(password, settings.CHANNEL_ENCRYPTION_KEY)
        if len(encrypted_password) > 500:
            raise ValueError("Mật khẩu SMTP quá dài.")
    else:
        encrypted_password = existing.get("password_encrypted", "")
    if not encrypted_password:
        raise ValueError("Nhập mật khẩu ứng dụng SMTP để bật gửi OTP bằng email shop.")

    values = {
        "enabled": "true",
        "host": host,
        "port": str(port),
        "security": security,
        "username": username,
        "password_encrypted": encrypted_password,
        "from_email": from_email,
        "from_name": from_name,
    }
    for key, value in values.items():
        setting_key = _PREFIX + key
        row = db.scalar(
            select(BusinessSetting).where(
                BusinessSetting.business_id == int(business_id),
                BusinessSetting.key == setting_key,
            )
        )
        if row is None:
            db.add(BusinessSetting(business_id=int(business_id), key=setting_key, value=value))
        else:
            row.value = value
    db.flush()
    return read_shop_otp_email(db, business_id)
