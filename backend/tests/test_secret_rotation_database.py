from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Business, Channel, Customer, CustomerContact, CustomerVerificationChallenge, User
from app.services.channel_credentials import decrypt_token, encrypt_token


_spec = importlib.util.spec_from_file_location(
    "p0_rotate_channel_secrets",
    Path(__file__).parents[1] / "scripts" / "rotate_channel_secrets.py",
)
_module = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_module)


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Business.metadata.create_all(engine)
    return engine


def _seed(engine, old_key: str):
    with Session(engine) as db:
        business = Business(name="Rotation shop", slug="rotation-shop")
        db.add(business)
        db.flush()
        user = User(
            business_id=business.id,
            full_name="Owner",
            email="owner@example.test",
            mfa_secret_encrypted=encrypt_token("mfa-seed", old_key),
        )
        channel = Channel(
            business_id=business.id,
            channel_type="zalo",
            name="Zalo OA",
            external_account_id="oa-rotation",
            status="active",
            access_token_encrypted=encrypt_token("provider-token", old_key),
            config={
                "provider": "zalo_oa",
                "oa_secret_key_encrypted": encrypt_token("oa-secret", old_key),
            },
        )
        customer = Customer(
            business_id=business.id,
            channel="zalo",
            external_user_id="customer-rotation",
            name="Rotation customer",
        )
        db.add_all([user, channel, customer])
        db.flush()
        contact = CustomerContact(
            business_id=business.id,
            customer_id=customer.id,
            kind="email",
            value_encrypted=encrypt_token("customer@example.test", old_key),
            value_hash=_module._contact_hash("email", "customer@example.test", old_key),
            masked_value="c***@example.test",
        )
        db.add(contact)
        db.flush()
        db.add(
            CustomerVerificationChallenge(
                business_id=business.id,
                customer_id=customer.id,
                contact_id=contact.id,
                channel="email",
                code_hash="one-way-hash",
                status="sent",
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(minutes=10),
            )
        )
        db.commit()


def test_rotation_dry_run_rolls_back_every_database_change():
    engine = _engine()
    old_key = "old-encryption-key"
    new_key = "new-encryption-key"
    _seed(engine, old_key)

    with Session(engine) as db:
        counts = _module.rotate_database_secrets(
            db, old_key=old_key, new_key=new_key, commit=False
        )

    assert counts == {
        "channels": 1,
        "channel_config_values": 1,
        "mfa_secrets": 1,
        "contacts": 1,
        "otp_challenges_expired": 1,
    }
    with Session(engine) as db:
        channel = db.scalar(select(Channel))
        challenge = db.scalar(select(CustomerVerificationChallenge))
        assert decrypt_token(channel.access_token_encrypted, old_key) == "provider-token"
        assert challenge.status == "sent"


def test_rotation_commit_reencrypts_all_material_and_expires_pending_otp():
    engine = _engine()
    old_key = "old-encryption-key"
    new_key = "new-encryption-key"
    _seed(engine, old_key)

    with Session(engine) as db:
        counts = _module.rotate_database_secrets(
            db, old_key=old_key, new_key=new_key, commit=True
        )

    assert counts["channels"] == 1
    assert counts["channel_config_values"] == 1
    assert counts["mfa_secrets"] == 1
    assert counts["contacts"] == 1
    assert counts["otp_challenges_expired"] == 1
    with Session(engine) as db:
        channel = db.scalar(select(Channel))
        user = db.scalar(select(User))
        contact = db.scalar(select(CustomerContact))
        challenge = db.scalar(select(CustomerVerificationChallenge))
        assert decrypt_token(channel.access_token_encrypted, new_key) == "provider-token"
        assert decrypt_token(channel.config["oa_secret_key_encrypted"], new_key) == "oa-secret"
        assert decrypt_token(user.mfa_secret_encrypted, new_key) == "mfa-seed"
        assert decrypt_token(contact.value_encrypted, new_key) == "customer@example.test"
        assert contact.value_hash == _module._contact_hash(
            "email", "customer@example.test", new_key
        )
        assert challenge.status == "expired"


def test_rotation_rejects_missing_or_reused_keys_before_touching_database():
    engine = _engine()
    with Session(engine) as db:
        for old_key, new_key in [("", "new"), ("same", "same")]:
            try:
                _module.rotate_database_secrets(
                    db, old_key=old_key, new_key=new_key, commit=True
                )
            except ValueError:
                pass
            else:
                raise AssertionError("unsafe key rotation was accepted")
