import hashlib
import hmac
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.monapay_webhooks import router
from app.core.config import settings
from app.db.dependencies import get_db
from app.database.session import Base
from app.models.monapay_transaction import MonaIncomingTransaction


@pytest.fixture
def webhook_app(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'monapay.db'}")
    Base.metadata.create_all(engine)
    db = Session(engine)
    monkeypatch.setattr(settings, "MONAPAY_WEBHOOK_SECRET", "test-webhook-secret-with-more-than-32-characters")
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app), db
    db.close()
    engine.dispose()


def signed_headers(body, timestamp=None):
    timestamp = str(int(time.time())) if timestamp is None else timestamp
    secret = settings.MONAPAY_WEBHOOK_SECRET.encode()
    signature = hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-Mona-Timestamp": timestamp, "X-Mona-Signature": f"sha256={signature}"}


def payload(**changes):
    value = {
        "amount": 250000,
        "description": "DON HANG DH-001",
        "transfer_date": "10:30:00 12/10/2026",
        "transaction_code": "FT-MONA-001",
        "account_number": "will-not-be-persisted",
        "bank_name": "ACB",
        "type": "income",
    }
    value.update(changes)
    return value


def test_webhook_verifies_raw_bytes_and_persists_without_account_number(webhook_app):
    client, db = webhook_app
    body = json.dumps(payload(), ensure_ascii=False, separators=(",", ":")).encode()

    response = client.post("/api/webhooks/monapay", content=body, headers=signed_headers(body))

    assert response.status_code == 200
    assert response.json() == {"accepted": True, "duplicate": False}
    record = db.scalar(select(MonaIncomingTransaction))
    assert record.transaction_code == "FT-MONA-001"
    assert record.amount == 250000
    assert record.is_sandbox is False
    assert not hasattr(record, "account_number")


def test_webhook_deduplicates_transaction_code(webhook_app):
    client, db = webhook_app
    body = json.dumps(payload(transaction_code="DUMMY123"), separators=(",", ":")).encode()
    headers = signed_headers(body)

    first = client.post("/api/webhooks/monapay", content=body, headers=headers)
    replay = client.post("/api/webhooks/monapay", content=body, headers=headers)

    assert first.status_code == replay.status_code == 200
    assert first.json()["duplicate"] is False
    assert replay.json()["duplicate"] is True
    assert db.query(MonaIncomingTransaction).count() == 1
    assert db.scalar(select(MonaIncomingTransaction)).is_sandbox is True


def test_webhook_rejects_bad_signature_and_old_timestamp(webhook_app):
    client, db = webhook_app
    body = json.dumps(payload(), separators=(",", ":")).encode()

    bad_signature = client.post("/api/webhooks/monapay", content=body,
                                headers={"X-Mona-Timestamp": str(int(time.time())), "X-Mona-Signature": "sha256=" + "0" * 64})
    expired = client.post("/api/webhooks/monapay", content=body,
                          headers=signed_headers(body, timestamp="1"))

    assert bad_signature.status_code == 401
    assert expired.status_code == 400
    assert db.query(MonaIncomingTransaction).count() == 0


def test_webhook_rejects_conflicting_reuse_of_transaction_code(webhook_app):
    client, db = webhook_app
    first_body = json.dumps(payload(), separators=(",", ":")).encode()
    second_body = json.dumps(payload(amount=1), separators=(",", ":")).encode()

    assert client.post("/api/webhooks/monapay", content=first_body, headers=signed_headers(first_body)).status_code == 200
    response = client.post("/api/webhooks/monapay", content=second_body, headers=signed_headers(second_body))

    assert response.status_code == 409
    assert db.query(MonaIncomingTransaction).count() == 1
