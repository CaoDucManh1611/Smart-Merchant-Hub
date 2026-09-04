import sys
import types

from app.core.config import settings
from app.rag.embedder import _embed_query_with_gemini, _embed_with_gemini


def _install_fake_gemini(monkeypatch, dimension: int):
    calls = []

    fake_api = types.ModuleType("google.generativeai")
    fake_api.configure = lambda **kwargs: None

    def embed_content(**kwargs):
        calls.append(kwargs)
        content = kwargs["content"]
        if isinstance(content, list):
            return {"embedding": [[0.0] * dimension for _ in content]}
        return {"embedding": [0.0] * dimension}

    fake_api.embed_content = embed_content
    fake_google = types.ModuleType("google")
    fake_google.__path__ = []
    fake_google.generativeai = fake_api
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_api)
    return calls


def test_gemini_embeddings_request_configured_output_dimension(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "test-key")
    calls = _install_fake_gemini(monkeypatch, 768)

    vectors = _embed_with_gemini(["catalog item"], "gemini-embedding-001")

    assert len(vectors[0]) == 768
    assert calls[0]["output_dimensionality"] == 768


def test_gemini_query_embedding_requests_same_output_dimension(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "test-key")
    calls = _install_fake_gemini(monkeypatch, 768)

    vector = _embed_query_with_gemini("catalog item", "gemini-embedding-001")

    assert len(vector) == 768
    assert calls[0]["output_dimensionality"] == 768
