import sys
import types

from app.core.config import settings
from app.rag.embedder import _embed_query_with_gemini, _embed_with_gemini


def _install_fake_gemini(monkeypatch, dimension: int):
    calls = []

    fake_api = types.ModuleType("google.genai")
    fake_types = types.ModuleType("google.genai.types")

    class EmbedContentConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    fake_types.EmbedContentConfig = EmbedContentConfig

    class Models:
        def embed_content(self, **kwargs):
            calls.append(kwargs)
            content = kwargs["contents"]
            values = [[0.0] * dimension for _ in content] if isinstance(content, list) else [[0.0] * dimension]
            return types.SimpleNamespace(
                embeddings=[types.SimpleNamespace(values=item) for item in values],
            )

    class Client:
        def __init__(self, **_kwargs):
            self.models = Models()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_api.Client = Client
    fake_api.types = fake_types
    fake_google = types.ModuleType("google")
    fake_google.__path__ = []
    fake_google.genai = fake_api
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_api)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    return calls


def test_gemini_embeddings_request_configured_output_dimension(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "test-key")
    calls = _install_fake_gemini(monkeypatch, 768)

    vectors = _embed_with_gemini(["catalog item"], "gemini-embedding-001")

    assert len(vectors[0]) == 768
    assert calls[0]["config"].output_dimensionality == 768
    assert calls[0]["config"].task_type == "RETRIEVAL_DOCUMENT"


def test_gemini_query_embedding_requests_same_output_dimension(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "test-key")
    calls = _install_fake_gemini(monkeypatch, 768)

    vector = _embed_query_with_gemini("catalog item", "gemini-embedding-001")

    assert len(vector) == 768
    assert calls[0]["config"].output_dimensionality == 768
    assert calls[0]["config"].task_type == "RETRIEVAL_QUERY"


def test_query_batch_uses_query_task_and_deduplicates(monkeypatch):
    from app.rag.embedder import embed_queries
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 3)
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "batch-test-key")
    calls = _install_fake_gemini(monkeypatch, 3)
    vectors = embed_queries(["hello", " hello ", "product price"])
    assert len(vectors) == 3 and len(calls) == 1
    assert calls[0]["contents"] == ["hello", "product price"]
    assert calls[0]["config"].task_type == "RETRIEVAL_QUERY"
    assert vectors[0] is not vectors[1]


def test_query_cache_is_success_only_copy_safe_and_model_scoped(monkeypatch):
    import pytest
    from app.rag import embedder
    embedder._cached_query_embedding.cache_clear()
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "test-space-a")
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 2)
    calls = []
    def encode(text, model):
        calls.append((text, model))
        if len(calls) == 1:
            raise RuntimeError("temporary failure")
        return [0.1, 0.2]
    monkeypatch.setattr(embedder, "_embed_query_with_local", encode)
    try:
        with pytest.raises(RuntimeError):
            embedder.embed_query("same query")
        first = embedder.embed_query("same query")
        first[0] = 999
        assert embedder.embed_query("same query") == [0.1, 0.2]
        assert len(calls) == 2
        monkeypatch.setattr(settings, "EMBEDDING_MODEL", "test-space-b")
        embedder.embed_query("same query")
        assert len(calls) == 3
        with pytest.raises(ValueError):
            embedder._validate_vectors([[float("nan"), 1.0]])
    finally:
        embedder._cached_query_embedding.cache_clear()
