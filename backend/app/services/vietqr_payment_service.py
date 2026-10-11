"""Local VietQR instructions. Receipts require administrator reconciliation."""
from binascii import crc_hqx
from datetime import timedelta
import secrets
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.setting import AppSetting
from app.models.subscription_payment_attempt import SubscriptionPaymentAttempt as Attempt
from app.services.platform_payment_settings import lock_configuration
from app.services.subscription_payment_service import lock_subscription, get_attempt, now, payment_status, quoted_amount

PREFIX = 'platform.vietqr.'
# Snapshot from https://api.vietqr.io/v2/banks, 2026-10-11; no runtime network dependency.
BANKS = dict(zip('970415 970436 970418 970405 970448 970422 970407 970416 970432 970423 970403 970437 970454 970441 970443 970431 970426 970400 970409 970412 970419 970424 970425 970427 970428 970430 970433 970438 970440 970446 970449 970452 668888 422589 970457'.split(), 'VietinBank Vietcombank BIDV Agribank OCB MBBank Techcombank ACB VPBank TPBank Sacombank HDBank BVBank VIB SHB Eximbank MSB SaigonBank BacABank PVcomBank NCB ShinhanBank ABBANK VietABank NamABank PGBank VietBank BaoVietBank SeABank COOPBANK LPBank KienLongBank KBank CIMB Woori'.split()))

class PaymentSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    bank_bin: str = Field(default='', max_length=6)
    account_number: str = Field(default='', max_length=34)
    account_name: str = Field(default='', max_length=100)

    @model_validator(mode='after')
    def validate_fields(self):
        for field in ('bank_bin', 'account_number', 'account_name'):
            value = getattr(self, field).strip()
            if any(ord(char) < 32 for char in value): raise ValueError('Invalid control character')
            setattr(self, field, value)
        if self.bank_bin and self.bank_bin not in BANKS: raise ValueError('Unsupported bank')
        if self.account_number and (not self.account_number.isascii() or not self.account_number.isdigit()):
            raise ValueError('Invalid account number')
        if self.enabled and not all((self.bank_bin, self.account_number, self.account_name)):
            raise ValueError('Bank details required')
        return self

def read(db):
    values = {row.key.removeprefix(PREFIX): row.value for row in db.scalars(select(AppSetting).where(AppSetting.key.startswith(PREFIX)))}
    return {'enabled': values.get('enabled') == 'true', 'provider': 'vietqr',
            'bank_bin': values.get('bank_bin', ''), 'account_number': values.get('account_number', ''),
            'account_name': values.get('account_name', ''), 'bank_name': BANKS.get(values.get('bank_bin'), ''),
            'bank_options': [{'bin': bin, 'name': name} for bin, name in BANKS.items()]}

def save(db, payload):
    lock_configuration(db)
    for field, value in payload.model_dump().items():
        value = ('true' if value else 'false') if field == 'enabled' else value
        row = db.get(AppSetting, PREFIX + field)
        if row is None: db.add(AppSetting(key=PREFIX + field, value=value))
        else: row.value = value
    db.flush()
    return read(db)

def configured(db):
    values = read(db)
    try:
        PaymentSettingsUpdate(**{key: values[key] for key in PaymentSettingsUpdate.model_fields})
        if not values['enabled']: raise ValueError('Disabled')
    except ValueError as error:
        raise HTTPException(503, detail={'code': 'payment_not_configured'}) from error
    return values

def qr_content(bank_bin, account_number, amount, reference):
    # NAPAS account transfer format; reference vectors: openhoangnc/vietqr (MIT).
    def field(tag, value):
        if not value.isascii() or len(value) > 99: raise ValueError('Invalid QR field')
        return f'{tag}{len(value):02d}{value}'
    recipient = field('00', bank_bin) + field('01', account_number)
    merchant = field('00', 'A000000727') + field('01', recipient) + field('02', 'QRIBFTTA')
    content = ('000201010211' + field('38', merchant) + field('53', '704') + field('54', str(amount))
               + field('58', 'VN') + field('62', field('08', reference)) + '6304')
    return content + f'{crc_hqx(content.encode("ascii"), 0xffff):04X}'

def create_payment(db, sub):
    sub = lock_subscription(db, sub.id)
    if sub.change_kind == 'downgrade': raise HTTPException(409, 'Downgrade does not require payment or refund')
    if sub.status not in {'pending', 'active'}: raise HTTPException(409, 'Subscription is no longer payable')
    attempt = get_attempt(db, sub.id)
    if payment_status(db, sub, attempt).status in {'paid', 'refunded'} or attempt is not None:
        return attempt
    lock_configuration(db)
    config = configured(db)
    amount = quoted_amount(sub)
    if sub.quoted_amount is None:
        sub.quoted_amount = amount
        sub.quoted_currency = 'VND'
    reference = f'SMH{sub.id}'
    attempt = Attempt(subscription_id=sub.id, order_code=secrets.randbelow(2**53-1)+1,
        amount=amount, currency='VND', status='pending', payment_link_id=f'vietqr:{sub.id}', reference=reference,
        bank_bin=config['bank_bin'], bank_name=config['bank_name'], account_number=config['account_number'],
        account_name=config['account_name'], qr_code=qr_content(config['bank_bin'], config['account_number'], amount, reference),
        expires_at=now()+timedelta(hours=24))
    db.add(attempt)
    try: db.commit()
    except IntegrityError as error:
        db.rollback()
        winner = get_attempt(db, sub.id)
        if winner is None: raise HTTPException(409, 'Payment order conflict; retry') from error
        return winner
    return attempt
