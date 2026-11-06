from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Business
from app.models.sales import Product
from app.services.auto_reply_service import (
    _match_customer_image_to_product,
    _match_customer_images_to_products,
)
from app.services.image_observation_cache import clear_image_observation_cache


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Business.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Product(id=1, business_id=1, sku="SHIRT-BLACK-M", name="Áo đen size M",
                    description="áo thun cotton màu đen size M", status="active",
                    metadata_={"image_url": "https://cdn.example/m.jpg", "attributes": {"size": "M", "color": "đen"}}),
            Product(id=2, business_id=1, sku="SHIRT-BLACK-L", name="Áo đen size L",
                    description="áo thun cotton màu đen size L", status="active",
                    metadata_={"image_url": "https://cdn.example/l.jpg", "attributes": {"size": "L", "color": "đen"}}),
            Product(id=3, business_id=2, sku="SHIRT-BLACK-M", name="Áo shop khác",
                    description="áo thun cotton màu đen size M", status="active",
                    metadata_={"image_url": "https://cdn.example/foreign.jpg"}),
        ])
        session.commit()
        yield session
    engine.dispose()


def test_image_match_is_tenant_scoped_and_variant_exact(db, monkeypatch):
    clear_image_observation_cache()
    responses = iter(["áo thun đen size L", '{"product_sku":"SHIRT-BLACK-L","confidence":0.96}'])
    monkeypatch.setattr("app.services.auto_reply_service.call_llm_with_image", lambda *a, **k: next(responses))
    monkeypatch.setattr("app.services.auto_reply_service.download_inbound_image_url",
                        lambda *a, **k: (b"reference", "image/jpeg"))
    matched, candidates, _ = _match_customer_image_to_product(
        db, business_id=1, image_bytes=b"customer", image_mime_type="image/jpeg",
    )
    assert matched.sku == "SHIRT-BLACK-L"
    assert {row.business_id for row in candidates} == {1}
    assert {row.sku for row in candidates} <= {"SHIRT-BLACK-M", "SHIRT-BLACK-L"}


def test_blurry_image_never_guesses_a_product(db, monkeypatch):
    clear_image_observation_cache()
    monkeypatch.setattr("app.services.auto_reply_service.call_llm_with_image", lambda *a, **k: "")
    matched, candidates, description = _match_customer_image_to_product(
        db, business_id=1, image_bytes=b"blur", image_mime_type="image/jpeg",
    )
    assert matched is None and candidates == [] and description == ""


def test_two_images_are_bounded_and_provider_failure_is_safe(db, monkeypatch):
    clear_image_observation_cache()
    matcher = Mock(side_effect=[
        (db.get(Product, 1), [db.get(Product, 1)], "áo size M"),
        RuntimeError("provider timeout"),
        AssertionError("third image must not run"),
    ])
    monkeypatch.setattr("app.services.auto_reply_service._match_customer_image_to_product", matcher)
    results = _match_customer_images_to_products(
        db, business_id=1,
        images=[(b"one", "image/jpeg"), (b"two", "image/png"), (b"three", "image/jpeg")],
    )
    assert [row["status"] for row in results] == ["matched", "provider_error"]
    assert matcher.call_count == 2


def test_image_catalog_flag_defaults_off():
    from app.core.config import settings
    assert settings.RAG_IMAGE_CATALOG_MATCH_ENABLED is False
