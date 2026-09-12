from unittest.mock import patch

import httpx
import pytest

from app.core.config import Settings
from app.services.otp_delivery import (
    OtpDeliveryNotConfigured,
    deliver_otp,
)


def test_disabled_delivery_is_safe_for_local_development():
    with patch("app.services.otp_delivery.settings", Settings(DATABASE_URL="sqlite:///./test.db", OTP_DELIVERY_MODE="disabled")):
        result = deliver_otp(channel="sms", destination="+84901234567", code="123456")

    assert result.provider == "disabled"
    assert result.delivered is False


def test_smtp_delivery_sends_message_without_logging_or_returning_code():
    config = Settings(
        DATABASE_URL="sqlite:///./test.db",
        OTP_DELIVERY_MODE="smtp",
        OTP_SMTP_HOST="smtp.example.test",
        OTP_SMTP_PORT=587,
        OTP_SMTP_USERNAME="mailer@example.test",
        OTP_SMTP_PASSWORD="secret",
        OTP_FROM_EMAIL="no-reply@example.test",
    )
    with patch("app.services.otp_delivery.settings", config), patch("app.services.otp_delivery.smtplib.SMTP") as smtp:
        result = deliver_otp(channel="email", destination="customer@example.test", code="123456")

    assert result.delivered is True
    assert result.provider == "smtp"
    message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
    assert message["To"] == "customer@example.test"
    assert "123456" in message.get_content()


def test_smtp_accepts_google_app_password_with_display_spaces():
    config = Settings(
        DATABASE_URL="sqlite:///./test.db",
        OTP_DELIVERY_MODE="smtp",
        OTP_SMTP_HOST="smtp.example.test",
        OTP_SMTP_PORT=587,
        OTP_SMTP_USERNAME="mailer@example.test",
        OTP_SMTP_PASSWORD="abcd efgh ijkl mnop",
        OTP_FROM_EMAIL="no-reply@example.test",
    )
    with patch("app.services.otp_delivery.settings", config), patch("app.services.otp_delivery.smtplib.SMTP") as smtp:
        result = deliver_otp(channel="email", destination="customer@example.test", code="123456")

    assert result.delivered is True
    smtp.return_value.__enter__.return_value.login.assert_called_once_with(
        "mailer@example.test", "abcdefghijklmnop"
    )


def test_twilio_delivery_posts_to_provider_without_exposing_credentials():
    config = Settings(
        DATABASE_URL="sqlite:///./test.db",
        OTP_DELIVERY_MODE="twilio",
        OTP_TWILIO_ACCOUNT_SID="AC123",
        OTP_TWILIO_AUTH_TOKEN="secret-token",
        OTP_TWILIO_FROM_NUMBER="+15005550006",
    )
    with patch("app.services.otp_delivery.settings", config), patch("app.services.otp_delivery.httpx.post") as post:
        post.return_value.raise_for_status.return_value = None
        result = deliver_otp(channel="sms", destination="+84901234567", code="123456")

    assert result.delivered is True
    assert result.provider == "twilio"
    kwargs = post.call_args.kwargs
    assert kwargs["auth"] == ("AC123", "secret-token")
    assert kwargs["data"]["To"] == "+84901234567"
    assert "123456" in kwargs["data"]["Body"]


def test_provider_configuration_errors_are_explicit():
    config = Settings(
        DATABASE_URL="sqlite:///./test.db",
        OTP_DELIVERY_MODE="smtp",
        OTP_DELIVERY_FALLBACK="disabled",
    )
    with patch("app.services.otp_delivery.settings", config), pytest.raises(OtpDeliveryNotConfigured):
        deliver_otp(channel="email", destination="customer@example.test", code="123456")


def test_smtp_requires_authenticated_sender_credentials_before_connecting():
    config = Settings(
        DATABASE_URL="sqlite:///./test.db",
        OTP_DELIVERY_MODE="smtp",
        OTP_SMTP_HOST="smtp.gmail.com",
        OTP_SMTP_PORT=587,
        OTP_FROM_EMAIL="thienshinn47@gmail.com",
        OTP_SMTP_USERNAME="",
        OTP_SMTP_PASSWORD="",
    )
    with patch("app.services.otp_delivery.settings", config), patch(
        "app.services.otp_delivery.smtplib.SMTP"
    ) as smtp, pytest.raises(OtpDeliveryNotConfigured, match="OTP_SMTP_USERNAME"):
        deliver_otp(channel="email", destination="customer@example.test", code="123456")

    smtp.assert_not_called()


def test_in_chat_delivery_is_available_for_a_free_development_demo():
    config = Settings(DATABASE_URL="sqlite:///./test.db", OTP_DELIVERY_MODE="in_chat")
    with patch("app.services.otp_delivery.settings", config):
        result = deliver_otp(channel="sms", destination="+84901234567", code="123456")

    assert result.provider == "in_chat"
    assert result.delivered is True
    assert result.reason == "development_demo"


def test_twilio_trial_can_fall_back_to_in_chat_when_provider_is_unavailable():
    config = Settings(
        DATABASE_URL="sqlite:///./test.db",
        OTP_DELIVERY_MODE="twilio",
        OTP_DELIVERY_FALLBACK="in_chat",
        OTP_TWILIO_ACCOUNT_SID="AC123",
        OTP_TWILIO_AUTH_TOKEN="secret-token",
        OTP_TWILIO_FROM_NUMBER="+15005550006",
    )
    with patch("app.services.otp_delivery.settings", config), patch(
        "app.services.otp_delivery.httpx.post",
        side_effect=httpx.ConnectError("provider unavailable"),
    ):
        result = deliver_otp(channel="sms", destination="+84901234567", code="123456")

    assert result.provider == "in_chat"
    assert result.delivered is True
    assert result.reason == "provider_fallback"
