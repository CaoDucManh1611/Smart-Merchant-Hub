from urllib.parse import parse_qs, urlparse
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.business_setting import BusinessSetting
from app.services.customer_collection_flow import _invoice_confirmation_prompt
from app.services.shop_bank_transfer import (
    BankTransferSettingsUpdate,
    order_transfer_instructions,
    order_qr_url,
    read_shop_bank_transfer,
    save_shop_bank_transfer,
    validate_shop_bank_transfer,
)
from app.services.vietnam_banks import BANKS


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    BusinessSetting.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_bank_settings_are_isolated_per_shop_and_make_order_qr(db):
    saved = save_shop_bank_transfer(
        db,
        101,
        BankTransferSettingsUpdate(
            enabled=True,
            bank_bin="970403",
            account_number="1234567890",
            account_name="SHOP TEST",
        ),
    )
    db.commit()

    assert saved["enabled"] is True
    assert saved["bank_name"] == "Sacombank"
    stored_account = db.query(BusinessSetting).filter_by(
        business_id=101, key="shop.bank_transfer.account_number_encrypted"
    ).one()
    assert stored_account.value != "1234567890"
    assert "1234567890" not in stored_account.value
    assert read_shop_bank_transfer(db, 202)["enabled"] is False
    message = order_transfer_instructions(
        db,
        business_id=101,
        order_number="DH-20261012-1",
        amount=349000,
    )
    assert "Số tiền: 349.000 đồng" in message
    assert "Nội dung chuyển khoản: DH202610121" in message
    assert "https://img.vietqr.io/image/970403-1234567890-compact2.png" in message


def test_qr_url_encodes_amount_reference_and_holder():
    url = order_qr_url(
        bank_bin="970403",
        account_number="1234567890",
        account_name="SHOP TEST",
        amount=125000,
        reference="DH-123",
    )
    query = parse_qs(urlparse(url).query)
    assert query == {"amount": ["125000"], "addInfo": ["DH123"], "accountName": ["SHOP TEST"]}


def test_local_bank_check_round_trips_qr_without_claiming_bank_verification():
    result = validate_shop_bank_transfer(BankTransferSettingsUpdate(
        enabled=False, bank_bin="970403", account_number="1234567890", account_name="SHOP TEST",
    ))
    assert result["status"] == "format_and_qr_valid"
    assert result["format_valid"] and result["qr_validated"]
    assert result["beneficiary_verified"] is False
    assert result["account_last4"] == "7890"
    assert "1234567890" not in str(result)


def test_enabling_bank_transfer_requires_supported_complete_details():
    with pytest.raises(ValidationError):
        BankTransferSettingsUpdate(enabled=True, bank_bin="970403")
    with pytest.raises(ValidationError):
        BankTransferSettingsUpdate(
            enabled=True,
            bank_bin="999999",
            account_number="12345678",
            account_name="SHOP",
        )


def test_local_check_returns_a_plain_message_when_bank_details_are_missing():
    payload = BankTransferSettingsUpdate(enabled=False)
    with pytest.raises(ValueError, match="Cần nhập ngân hàng, số tài khoản và tên chủ tài khoản"):
        validate_shop_bank_transfer(payload)


def test_vietqr_selector_includes_transfer_enabled_banks():
    assert len(BANKS) == 47
    assert BANKS["970429"] == "SCB"
    assert BANKS["970463"] == "KookminHCM"


def test_unconfigured_shop_does_not_get_a_fake_qr(db):
    message = order_transfer_instructions(
        db,
        business_id=303,
        order_number="DH-303",
        amount=50000,
    )
    assert "chưa cài thông tin" in message
    assert "img.vietqr.io" not in message


def test_invoice_prompt_shows_qr_only_for_bank_transfer(db):
    save_shop_bank_transfer(
        db,
        404,
        BankTransferSettingsUpdate(
            enabled=True,
            bank_bin="970403",
            account_number="1234567890",
            account_name="SHOP TEST",
        ),
    )
    order = SimpleNamespace(order_number="DH-404", items=[], total_amount=125000)

    transfer_prompt = _invoice_confirmation_prompt(
        order, payment_method="bank_transfer", db=db, business_id=404
    )
    cod_prompt = _invoice_confirmation_prompt(order, payment_method="cod", db=db, business_id=404)

    assert "Mã QR: https://img.vietqr.io/image/970403-1234567890-compact2.png" in transfer_prompt
    assert "Nội dung chuyển khoản: DH404" in transfer_prompt
    assert "sau khi xác nhận tiền đã vào tài khoản" in transfer_prompt
    assert "img.vietqr.io" not in cod_prompt
