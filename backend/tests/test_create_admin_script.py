import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business
from scripts import create_admin


def test_create_admin_prints_result_after_session_closes(monkeypatch, capsys):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Business.metadata.create_all(engine)

    monkeypatch.setattr(create_admin, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda _prompt: "safe-password")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_admin.py",
            "--business-id",
            "1",
            "--email",
            "owner@example.com",
            "--name",
            "Shop Owner",
        ],
    )

    with Session(engine) as db:
        db.add(Business(id=1, name="Shop", slug="shop"))
        db.commit()

    assert create_admin.main() == 0
    assert "Created owner user" in capsys.readouterr().out
