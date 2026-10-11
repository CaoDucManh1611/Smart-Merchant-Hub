import time

from sqlalchemy import Float, cast, select, update

from app.core.config import settings
from app.models.setting import AppSetting
from app.services.channel_credentials import decrypt_token, encrypt_token
from app.services.otp_delivery import OtpDeliveryNotConfigured, OtpSmtpConfig

PREFIX = "platform.otp.smtp."


def values(db):
    return {row.key.removeprefix(PREFIX): row.value for row in db.scalars(
        select(AppSetting).where(AppSetting.key.startswith(PREFIX)))}


def read_platform_otp_email(db):
    saved = values(db)
    return {"enabled": saved.get("enabled") == "true", "host": "smtp.gmail.com", "port": 587,
            "security": "starttls", "username": saved.get("username", ""),
            "from_email": saved.get("from_email", ""), "from_name": saved.get("from_name", "Smart Merchant Hub"),
            "password_configured": bool(saved.get("password_encrypted"))}


def save_platform_otp_email(db, payload):
    # Serialize updates to the existing singleton settings, including blank-password retention.
    db.scalars(select(AppSetting).where(AppSetting.key.startswith(PREFIX)).with_for_update()).all()
    saved = values(db)
    password = "".join(payload.password.split())
    encrypted = encrypt_token(password, settings.CHANNEL_ENCRYPTION_KEY) if password else saved.get("password_encrypted", "")
    if payload.enabled and not encrypted:
        raise ValueError("A Gmail app password is required")
    updated = {"enabled": "true" if payload.enabled else "false", "username": payload.username,
               "from_email": payload.from_email, "from_name": payload.from_name,
               "password_encrypted": encrypted}
    for key, value in updated.items():
        row = db.get(AppSetting, PREFIX + key)
        if row is None:
            db.add(AppSetting(key=PREFIX + key, value=value))
        else:
            row.value = value
    db.flush()
    if db.get(AppSetting, PREFIX + "last_test_at") is None:
        db.add(AppSetting(key=PREFIX + "last_test_at", value="0"))
        db.flush()
    return read_platform_otp_email(db)


def claim_test_email_slot(db):
    # A committed conditional update shares the cooldown across workers and recipients.
    now = time.time()
    key = PREFIX + "last_test_at"
    if db.get(AppSetting, key) is None:
        db.add(AppSetting(key=key, value="0"))
        db.flush()
    claimed = db.execute(update(AppSetting).where(
        AppSetting.key == key, cast(AppSetting.value, Float) <= now - 60
    ).values(value=str(now))).rowcount == 1
    db.commit()
    return claimed


def get_platform_otp_smtp_config(db):
    saved = values(db)
    if saved.get("enabled") != "true":
        return None
    try:
        password = decrypt_token(saved["password_encrypted"], settings.CHANNEL_ENCRYPTION_KEY)
        if not password or not saved["username"] or not saved["from_email"]:
            raise ValueError("Incomplete sender")
        return OtpSmtpConfig(host="smtp.gmail.com", port=587, security="starttls",
            username=saved["username"], password=password, from_email=saved["from_email"],
            from_name=saved.get("from_name", "Smart Merchant Hub"))
    except Exception as error:
        raise OtpDeliveryNotConfigured("Platform OTP sender is unavailable") from error


