"""Provider-backed OTP delivery with a safe development fallback.

The checkout flow stores only a hash of the code.  This module is the single
place allowed to hand the short-lived code to an external delivery provider;
it never logs or returns the code.  Production credentials must come from the
secret manager through the settings object.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
import logging
import ssl
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


@dataclass(frozen=True)
class OtpSmtpConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str = ""
    security: str = "starttls"


def _message(
    code: str,
    *,
    purpose: str = "verification",
    shop_name: str | None = None,
    shop_slug: str | None = None,
) -> str:
    if purpose == "order_confirmation":
        return f"Mã OTP xác nhận đơn hàng Smart Merchant Hub của bạn là {code}. Mã có hiệu lực trong 10 phút."
    if purpose == "team_invite":
        safe_shop_name = " ".join(str(shop_name or "Smart Merchant Hub").split())
        safe_shop_slug = " ".join(str(shop_slug or "").split())
        login_hint = f"Mã shop đăng nhập: {safe_shop_slug}\n" if safe_shop_slug else ""
        return (
            f"Bạn đang được thêm vào đội ngũ shop {safe_shop_name}.\n"
            f"{login_hint}"
            f"Mã OTP xác minh: {code}\n"
            "Mã có hiệu lực trong 10 phút. Không chia sẻ mã này với người khác."
        )
    return f"Mã xác thực Smart Merchant Hub của bạn là {code}. Mã có hiệu lực trong 10 phút."


def _html_message(
    code: str,
    *,
    purpose: str,
    shop_name: str | None = None,
    shop_slug: str | None = None,
) -> str:
    safe_code = escape(str(code))
    if purpose == "team_invite":
        safe_shop_name = escape(" ".join(str(shop_name or "Smart Merchant Hub").split()))
        safe_shop_slug = escape(" ".join(str(shop_slug or "").split()))
        shop_slug_html = (
            f'<div style="margin-top:8px;color:#526b70;font-size:13px">Mã shop đăng nhập: '
            f'<strong style="color:#087d79">{safe_shop_slug}</strong></div>'
            if safe_shop_slug else ""
        )
        shop_details = f"""
          <tr><td style="padding:0 28px 18px">
            <div style="padding:16px 18px;border:1px solid #cfe5e3;border-radius:12px;background:#f3faf9">
              <div style="color:#60777b;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase">CỬA HÀNG</div>
              <div style="margin-top:6px;color:#173b42;font-size:18px;font-weight:700">{safe_shop_name}</div>
              {shop_slug_html}
            </div>
          </td></tr>"""
        heading = "Xác minh tài khoản nhân viên"
        intro = "Bạn đang được thêm vào đội ngũ shop. Hãy kiểm tra đúng cửa hàng và dùng mã shop ở trên khi đăng nhập nếu hệ thống yêu cầu."
        code_label = "MÃ XÁC MINH NHÂN VIÊN"
    elif purpose == "order_confirmation":
        shop_details = ""
        heading = "Xác nhận đơn hàng"
        intro = "Dùng mã xác minh bên dưới để tiếp tục xác nhận đơn hàng của bạn."
        code_label = "MÃ XÁC NHẬN ĐƠN HÀNG"
    else:
        shop_details = ""
        heading = "Xác minh email"
        intro = "Dùng mã xác minh bên dưới để tiếp tục."
        code_label = "MÃ XÁC MINH"

    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:24px 12px;background:#f2f6f6;font-family:Arial,Helvetica,sans-serif;color:#173b42">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;margin:0 auto;border:1px solid #dce7e7;border-radius:16px;background:#fff;overflow:hidden">
    <tr><td style="padding:22px 28px;background:#123f43;color:#fff">
      <div style="font-size:12px;font-weight:700;letter-spacing:.12em;color:#8de0d8">SMART MERCHANT HUB</div>
      <div style="margin-top:9px;font-size:21px;font-weight:700">{heading}</div>
    </td></tr>
    <tr><td style="padding:24px 28px 16px;font-size:15px;line-height:1.65">{intro}</td></tr>
    {shop_details}
    <tr><td style="padding:0 28px 8px;color:#60777b;font-size:12px;font-weight:700;letter-spacing:.08em">{code_label}</td></tr>
    <tr><td style="padding:0 28px 20px">
      <div style="padding:17px 12px;border:1px solid #cfe5e3;border-radius:12px;background:#f3faf9;text-align:center;color:#087d79;font-size:32px;font-weight:700;letter-spacing:.32em">{safe_code}</div>
    </td></tr>
    <tr><td style="padding:0 28px 24px;color:#526b70;font-size:13px;line-height:1.6">Mã có hiệu lực trong <strong>10 phút</strong>. Vì bảo mật, không chia sẻ mã này với bất kỳ ai.</td></tr>
    <tr><td style="padding:16px 28px;border-top:1px solid #e7eeee;color:#829396;font-size:11px;line-height:1.5">Email tự động từ Smart Merchant Hub. Nếu bạn không thực hiện yêu cầu này, hãy bỏ qua email.</td></tr>
  </table>
</body></html>"""


def _send_smtp(
    *,
    destination: str,
    code: str,
    smtp_config: OtpSmtpConfig | None = None,
    purpose: str = "verification",
    shop_name: str | None = None,
    shop_slug: str | None = None,
) -> None:
    host = (smtp_config.host if smtp_config else settings.OTP_SMTP_HOST).strip()
    sender = (smtp_config.from_email if smtp_config else settings.OTP_FROM_EMAIL).strip()
    if not host or not sender:
        raise OtpDeliveryNotConfigured("OTP_SMTP_HOST và OTP_FROM_EMAIL là bắt buộc.")
    username = (smtp_config.username if smtp_config else settings.OTP_SMTP_USERNAME).strip()
    # Google displays App Passwords as four-character groups (for example
    # ``abcd efgh ijkl mnop``).  SMTP expects the underlying 16-character
    # secret, so ignore display whitespace while preserving every other byte.
    password = "".join(str(smtp_config.password if smtp_config else settings.OTP_SMTP_PASSWORD).split())
    if not username or not password:
        raise OtpDeliveryNotConfigured(
            "OTP_SMTP_USERNAME và OTP_SMTP_PASSWORD (App Password của tài khoản gửi) là bắt buộc."
        )
    message = EmailMessage()
    message["From"] = formataddr(("Smart Merchant Hub", sender))
    message["To"] = destination
    is_order_confirmation = purpose == "order_confirmation"
    if purpose == "test":
        message["Subject"] = "Kiểm tra cấu hình email Smart Merchant Hub"
        message.set_content("Đây là email thử để kiểm tra máy chủ SMTP. Không cần trả lời thư này.")
    else:
        if purpose == "team_invite":
            safe_shop_name = " ".join(str(shop_name or "").split())
            message["Subject"] = f"Mã OTP nhân viên - {safe_shop_name}" if safe_shop_name else "Mã OTP nhân viên Smart Merchant Hub"
        else:
            message["Subject"] = (
                "Mã OTP xác nhận đơn hàng Smart Merchant Hub"
                if is_order_confirmation else "Mã xác thực Smart Merchant Hub"
            )
        message.set_content(_message(
            code,
            purpose=purpose,
            shop_name=shop_name,
            shop_slug=shop_slug,
        ))
        message.add_alternative(_html_message(
            code,
            purpose=purpose,
            shop_name=shop_name,
            shop_slug=shop_slug,
        ), subtype="html")
    port = int(smtp_config.port if smtp_config else settings.OTP_SMTP_PORT)
    security = smtp_config.security if smtp_config else ("starttls" if settings.OTP_SMTP_USE_TLS else "none")
    if security == "ssl":
        client_factory = lambda: smtplib.SMTP_SSL(host, port, timeout=10, context=ssl.create_default_context())
    else:
        client_factory = lambda: smtplib.SMTP(host, port, timeout=10)
    with client_factory() as client:
        if security == "starttls":
            client.starttls(context=ssl.create_default_context())
        client.login(username, password)
        client.send_message(message)


def send_smtp_test_email(*, destination: str, smtp_config: OtpSmtpConfig) -> OtpDeliveryResult:
    """Send a non-OTP probe; success means SMTP accepted it, not Inbox delivery."""
    try:
        _send_smtp(destination=destination, code="", smtp_config=smtp_config, purpose="test")
    except (OtpDeliveryNotConfigured, OtpDeliveryError):
        raise
    except (OSError, smtplib.SMTPException) as error:
        raise OtpDeliveryError("Không thể gửi email thử qua SMTP.") from error
    return OtpDeliveryResult(provider="smtp", delivered=True)


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


def deliver_otp(
    *,
    channel: OtpChannel,
    destination: str,
    code: str,
    smtp_config: OtpSmtpConfig | None = None,
    purpose: str = "verification",
    shop_name: str | None = None,
    shop_slug: str | None = None,
) -> OtpDeliveryResult:
    """Deliver an OTP using the configured provider.

    ``disabled`` is intentionally accepted for local development.  It lets
    tests exercise the full state machine without making an external call.
    ``in_chat`` is a free development transport: the checkout flow includes
    the code in the bot's current Telegram/Zalo chat and never enables it in
    production.  Production runbooks should use ``smtp`` for email or
    ``twilio`` for SMS.
    """

    mode = "smtp" if channel == "email" and smtp_config is not None else settings.OTP_DELIVERY_MODE.strip().lower()
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
            _send_smtp(
                destination=destination,
                code=code,
                smtp_config=smtp_config,
                purpose=purpose,
                shop_name=shop_name,
                shop_slug=shop_slug,
            )
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

