"""RAG seed must be explicitly scoped to one provisioned shop."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_startup_does_not_seed_every_active_shop():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "seed_knowledge_base" not in source


def test_seed_service_requires_an_explicit_business_id():
    source = (ROOT / "app" / "services" / "knowledge_seed_service.py").read_text(encoding="utf-8")
    assert "business_id is None" in source
    assert "refusing global" in source.lower()
