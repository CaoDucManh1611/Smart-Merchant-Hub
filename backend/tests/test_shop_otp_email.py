from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.models.business_setting import BusinessSetting
from app.services.otp_delivery import OtpSmtpConfig, deliver_otp
from app.services.shop_otp_email import (
    get_shop_otp_smtp_config,
    read_shop_otp_email,
    save_shop_otp_email,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    BusinessSetting.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _payload(**overrides):
    return {
        "enabled": True,
        "host": "smtp.gmail.com",
        "port": 587,
        "security": "starttls",
        "username": "info@gmail.com",
        "password": "google-app-password",
        "from_email": "info@gmail.com",
        "from_name": "Shop Hồng",
        **overrides,
    }


def test_shop_smtp_secret_is_encrypted_and_tenant_scoped(db, monkeypatch):
    monkeypatch.setattr(settings, "CHANNEL_ENCRYPTION_KEY", "test-encryption-key")

    result = save_shop_otp_email(db, 21, _payload())

    assert result["enabled"] is True
    assert result["password_configured"] is True
    assert read_shop_otp_email(db, 22)["enabled"] is False
    encrypted = db.scalar(
        select(BusinessSetting.value).where(
            BusinessSetting.business_id == 21,
            BusinessSetting.key == "otp.smtp.password_encrypted",
        )
    )
    assert encrypted != "google-app-password"
    assert get_shop_otp_smtp_config(db, 21).password == "google-app-password"
    assert get_shop_otp_smtp_config(db, 22) is None


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"from_email": "not-an-email"}, "Email gửi không hợp lệ"),
        ({"host": "not a host"}, "tên máy chủ SMTP"),
        ({"port": 25}, "cổng 587"),
        ({"port": 587, "security": "ssl"}, "cổng 587"),
    ],
)
def test_shop_smtp_rejects_unsafe_or_mismatched_sender_settings(db, monkeypatch, changes, error):
    monkeypatch.setattr(settings, "CHANNEL_ENCRYPTION_KEY", "test-encryption-key")
    with pytest.raises(ValueError, match=error):
        save_shop_otp_email(db, 21, _payload(**changes))


def test_disabling_shop_smtp_removes_the_saved_secret(db, monkeypatch):
    monkeypatch.setattr(settings, "CHANNEL_ENCRYPTION_KEY", "test-encryption-key")
    save_shop_otp_email(db, 21, _payload())

    result = save_shop_otp_email(db, 21, {"enabled": False})

    assert result["enabled"] is False
    assert result["password_configured"] is False
    assert get_shop_otp_smtp_config(db, 21) is None


def test_shop_smtp_overrides_global_otp_sender_and_uses_shop_display_name():
    config = Settings(
        DATABASE_URL="sqlite:///./test.db",
        OTP_DELIVERY_MODE="disabled",
        CHANNEL_ENCRYPTION_KEY="test-encryption-key",
    )
    smtp_config = OtpSmtpConfig(
        host="smtp.gmail.com",
        port=587,
        username="info@gmail.com",
        password="google-app-password",
        from_email="info@gmail.com",
        from_name="Shop Hồng",
    )
    with patch("app.services.otp_delivery.settings", config), patch("app.services.otp_delivery.smtplib.SMTP") as smtp:
        result = deliver_otp(
            channel="email",
            destination="staff@example.com",
            code="123456",
            smtp_config=smtp_config,
        )

    assert result.provider == "smtp"
    message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
    assert message["From"].addresses[0].display_name == "Shop Hồng"
    assert message["From"].addresses[0].addr_spec == "info@gmail.com"
    assert message["To"] == "staff@example.com"
    smtp.return_value.__enter__.return_value.login.assert_called_once_with("info@gmail.com", "google-app-password")


def test_shop_smtp_uses_ssl_for_port_465():
    config = Settings(DATABASE_URL="sqlite:///./test.db", CHANNEL_ENCRYPTION_KEY="test-encryption-key")
    smtp_config = OtpSmtpConfig(
        host="smtp.example.com", port=465, security="ssl", username="user@example.com",
        password="secret", from_email="sender@example.com",
    )
    with patch("app.services.otp_delivery.settings", config), \
         patch("app.services.otp_delivery.smtplib.SMTP_SSL") as smtp_ssl, \
         patch("app.services.otp_delivery.smtplib.SMTP") as smtp:
        deliver_otp(channel="email", destination="staff@example.com", code="123456", smtp_config=smtp_config)
    smtp_ssl.assert_called_once()
    smtp.assert_not_called()


def test_shop_smtp_accepts_custom_domain_and_ssl_port(db, monkeypatch):
    monkeypatch.setattr(settings, "CHANNEL_ENCRYPTION_KEY", "test-encryption-key")
    result = save_shop_otp_email(db, 21, _payload(
        host="smtp.mail.example.com", port=465, security="ssl",
        username="mailer@example.com", from_email="info@example.com",
    ))
    assert result["host"] == "smtp.mail.example.com"
    assert result["security"] == "ssl"
    assert get_shop_otp_smtp_config(db, 21).from_email == "info@example.com"
