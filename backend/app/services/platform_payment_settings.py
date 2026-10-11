"""Encrypted platform payment configuration, resolved per request."""
from types import SimpleNamespace
from urllib.parse import urlparse

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, text

from app.core.config import settings
from app.models.setting import AppSetting
from app.services.channel_credentials import decrypt_token, encrypt_token

PREFIX = 'platform.payment.'
FIELDS = {'client_id': 'PAYOS_CLIENT_ID', 'api_key': 'PAYOS_API_KEY',
          'checksum_key': 'PAYOS_CHECKSUM_KEY', 'return_url': 'PAYOS_RETURN_URL',
          'cancel_url': 'PAYOS_CANCEL_URL', 'account_number': 'PAYOS_EXPECTED_ACCOUNT_NUMBER',
          'bank_bin': 'PAYOS_EXPECTED_BANK_BIN'}
SECRETS = {'api_key', 'checksum_key'}


class PaymentSettingsUpdate(BaseModel):
    enabled: bool = False
    client_id: str = Field(default='', max_length=255)
    api_key: str = Field(default='', max_length=200)
    checksum_key: str = Field(default='', max_length=200)
    return_url: str = Field(default='', max_length=400)
    cancel_url: str = Field(default='', max_length=400)
    account_number: str = Field(default='', max_length=40)
    bank_bin: str = Field(default='', max_length=6)
    account_name: str = Field(default='', max_length=255)

    @model_validator(mode='after')
    def validate_fields(self):
        for field in FIELDS.keys() | {'account_name'}:
            value = getattr(self, field).strip()
            if any(ord(char) < 32 for char in value):
                raise ValueError('Invalid control character')
            setattr(self, field, value)
        for field in ('return_url', 'cancel_url'):
            value = getattr(self, field)
            if value:
                url = urlparse(value)
                if url.scheme != 'https' or not url.hostname or url.username or url.password:
                    raise ValueError('HTTPS return and cancel URLs required')
        if self.account_number and (not self.account_number.isascii() or not self.account_number.isdigit()):
            raise ValueError('Invalid bank account')
        if self.bank_bin and (len(self.bank_bin) != 6 or not self.bank_bin.isascii() or not self.bank_bin.isdigit()):
            raise ValueError('Bank BIN must have six digits')
        return self


def stored(db):
    return {row.key.removeprefix(PREFIX): row.value for row in db.scalars(
        select(AppSetting).where(AppSetting.key.startswith(PREFIX)))}


def read(db):
    values = stored(db)
    result = {'enabled': values.get('enabled') == 'true', 'account_name': values.get('account_name', '')}
    for field, env in FIELDS.items():
        if field in SECRETS:
            result[field + '_configured'] = bool(values.get(field + '_encrypted') or (not values and getattr(settings, env)))
        else:
            result[field] = values.get(field, getattr(settings, env) if not values else '')
    return result


def lock_configuration(db):
    if db.get_bind().dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(72401831)'))


def save(db, payload):
    lock_configuration(db)
    db.scalars(select(AppSetting).where(AppSetting.key.startswith(PREFIX)).with_for_update()).all()
    old = stored(db)
    values = payload.model_dump()
    previous = resolve(db)
    # shortcut: freeze provider identity after the first order; version keys before supporting rotation.
    from app.models.subscription_payment_attempt import SubscriptionPaymentAttempt
    critical = ('client_id', 'api_key', 'checksum_key', 'account_number', 'bank_bin')
    changed = any((values[field] or getattr(previous, FIELDS[field]) if field in SECRETS else values[field])
                  != getattr(previous, FIELDS[field]) for field in critical)
    if changed and db.scalar(select(SubscriptionPaymentAttempt.id).limit(1)):
        raise ValueError('Provider identity cannot change after payment orders exist')
    for field in SECRETS:
        secret = values.pop(field)
        encrypted = encrypt_token(secret, settings.CHANNEL_ENCRYPTION_KEY) if secret else old.get(field + '_encrypted', '')
        if not encrypted and not old and getattr(settings, FIELDS[field]):
            encrypted = encrypt_token(getattr(settings, FIELDS[field]), settings.CHANNEL_ENCRYPTION_KEY)
        values[field + '_encrypted'] = encrypted
    if payload.enabled and any(not values.get(field + '_encrypted' if field in SECRETS else field) for field in FIELDS):
        raise ValueError('Incomplete payment configuration')
    for field, value in values.items():
        value = ('true' if value else 'false') if field == 'enabled' else value
        row = db.get(AppSetting, PREFIX + field)
        if row is None:
            db.add(AppSetting(key=PREFIX + field, value=value))
        else:
            row.value = value
    db.flush()
    return read(db)


def resolve(db, *, require_enabled=False):
    values = stored(db)
    if require_enabled and values and values.get('enabled') != 'true':
        raise HTTPException(503, detail={'code': 'payment_not_configured'})
    result = {env: getattr(settings, env) for env in FIELDS.values()}
    result['PAYOS_PAYMENT_TTL_SECONDS'] = settings.PAYOS_PAYMENT_TTL_SECONDS
    if values:
        try:
            for field, env in FIELDS.items():
                result[env] = decrypt_token(values[field + '_encrypted'], settings.CHANNEL_ENCRYPTION_KEY) if field in SECRETS and values.get(field + '_encrypted') else values.get(field, '')
        except Exception as error:
            raise HTTPException(503, detail={'code': 'payment_not_configured'}) from error
    return SimpleNamespace(**result)
