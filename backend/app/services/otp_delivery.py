"""Provider-backed OTP delivery with a safe development fallback.

The checkout flow stores only a hash of the code.  This module is the single
place allowed to hand the short-lived code to an external delivery provider;
it never logs or returns the code.  Production credentials must come from the
secret manager through the settings object.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import logging
import smtplib
from typing import Literal

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)
OtpChannel = Literal["sms", "email"]


class OtpDeliveryNotConfigured(RuntimeError):
    """The selected provider is not configured with the required secrets."""


class OtpDeliveryError(RuntimeError):
    """The configured provider rejected or could not deliver the message."""


@dataclass(frozen=True)
class OtpDeliveryResult:
    provider: str
    delivered: bool
    reason: str | None = None


def _message(code: str) -> str:
    # Keep the content deliberately generic; never include customer data.
    return f"Mã xác thực Smart Merchant Hub của bạn là {code}. Mã có hiệu lực trong 10 phút."


def _send_smtp(*, destination: str, code: str) -> None:
    host = settings.OTP_SMTP_HOST.strip()
    sender = settings.OTP_FROM_EMAIL.strip()
    if not host or not sender:
        raise OtpDeliveryNotConfigured("OTP_SMTP_HOST và OTP_FROM_EMAIL là bắt buộc.")
    username = settings.OTP_SMTP_USERNAME.strip()
    # Google displays App Passwords as four-character groups (for example
    # ``abcd efgh ijkl mnop``).  SMTP expects the underlying 16-character
    # secret, so ignore display whitespace while preserving every other byte.
    password = "".join(str(settings.OTP_SMTP_PASSWORD).split())
    if not username or not password:
        raise OtpDeliveryNotConfigured(
            "OTP_SMTP_USERNAME và OTP_SMTP_PASSWORD (App Password của tài khoản gửi) là bắt buộc."
        )
    message = EmailMessage()
    message["From"] = sender
    message["To"] = destination
    message["Subject"] = "Mã xác thực Smart Merchant Hub"
    message.set_content(_message(code))
    with smtplib.SMTP(host, int(settings.OTP_SMTP_PORT), timeout=10) as client:
        if settings.OTP_SMTP_USE_TLS:
            client.starttls()
        client.login(username, password)
        client.send_message(message)


def _send_twilio(*, destination: str, code: str) -> None:
    sid = settings.OTP_TWILIO_ACCOUNT_SID.strip()
    token = settings.OTP_TWILIO_AUTH_TOKEN.strip()
    sender = settings.OTP_TWILIO_FROM_NUMBER.strip()
    if not sid or not token or not sender:
        raise OtpDeliveryNotConfigured(
            "OTP_TWILIO_ACCOUNT_SID, OTP_TWILIO_AUTH_TOKEN và OTP_TWILIO_FROM_NUMBER là bắt buộc."
        )
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    response = httpx.post(
        url,
        data={"From": sender, "To": destination, "Body": _message(code)},
        auth=(sid, token),
        timeout=10,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPError as error:
        # Do not include response bodies: Twilio responses can contain phone
        # numbers or provider credentials in diagnostic fields.
        raise OtpDeliveryError("Nhà cung cấp SMS từ chối gửi OTP.") from error


def deliver_otp(*, channel: OtpChannel, destination: str, code: str) -> OtpDeliveryResult:
    """Deliver an OTP using the configured provider.

    ``disabled`` is intentionally accepted for local development.  It lets
    tests exercise the full state machine without making an external call.
    ``in_chat`` is a free development transport: the checkout flow includes
    the code in the bot's current Telegram/Zalo chat and never enables it in
    production.  Production runbooks should use ``smtp`` for email or
    ``twilio`` for SMS.
    """

    mode = settings.OTP_DELIVERY_MODE.strip().lower()
    if mode in {"", "disabled", "none"}:
        return OtpDeliveryResult(provider="disabled", delivered=False, reason="disabled")
    if mode == "in_chat":
        if settings.ENVIRONMENT.strip().lower() == "production":
            raise OtpDeliveryNotConfigured("In-chat OTP chỉ được phép trong development.")
        return OtpDeliveryResult(provider="in_chat", delivered=True, reason="development_demo")
    if mode == "smtp":
        if channel != "email":
            raise OtpDeliveryNotConfigured("SMTP chỉ dùng cho OTP email.")
        try:
            _send_smtp(destination=destination, code=code)
        except (OtpDeliveryNotConfigured, OtpDeliveryError) as error:
            if settings.OTP_DELIVERY_FALLBACK.strip().lower() == "in_chat":
                logger.warning("OTP email delivery fell back to in-chat demo: error_type=%s", type(error).__name__)
                return OtpDeliveryResult(provider="in_chat", delivered=True, reason="provider_fallback")
            raise
        except (OSError, smtplib.SMTPException) as error:
            logger.warning("OTP email delivery failed: provider=smtp error_type=%s", type(error).__name__)
            if settings.OTP_DELIVERY_FALLBACK.strip().lower() == "in_chat":
                return OtpDeliveryResult(provider="in_chat", delivered=True, reason="provider_fallback")
            raise OtpDeliveryError("Không thể gửi OTP email.") from error
        return OtpDeliveryResult(provider="smtp", delivered=True)
    if mode == "twilio":
        if channel != "sms":
            raise OtpDeliveryNotConfigured("Twilio chỉ dùng cho OTP SMS.")
        try:
            _send_twilio(destination=destination, code=code)
        except (OtpDeliveryNotConfigured, OtpDeliveryError) as error:
            if settings.OTP_DELIVERY_FALLBACK.strip().lower() == "in_chat":
                logger.warning("OTP SMS delivery fell back to in-chat demo: error_type=%s", type(error).__name__)
                return OtpDeliveryResult(provider="in_chat", delivered=True, reason="provider_fallback")
            raise
        except (OSError, httpx.HTTPError) as error:
            logger.warning("OTP SMS delivery failed: provider=twilio error_type=%s", type(error).__name__)
            if settings.OTP_DELIVERY_FALLBACK.strip().lower() == "in_chat":
                return OtpDeliveryResult(provider="in_chat", delivered=True, reason="provider_fallback")
            raise OtpDeliveryError("Không thể gửi OTP SMS.") from error
        return OtpDeliveryResult(provider="twilio", delivered=True)
    raise OtpDeliveryNotConfigured("OTP_DELIVERY_MODE phải là disabled, smtp hoặc twilio.")

