import asyncio
from unittest.mock import Mock

import pytest

from app.rag import llm_caller as llm
from app.services.api_key_pool import ApiKeyPoolUnavailable
from app.services.provider_circuit_breaker import ProviderCircuitBreaker


@pytest.fixture
def fallback(monkeypatch):
    monkeypatch.setattr(llm, "_model_breaker", ProviderCircuitBreaker(failure_threshold=1, recovery_timeout=60))
    monkeypatch.setattr(llm.settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(llm.settings, "LLM_API_KEYS", "groq-only-key")
    monkeypatch.setattr(llm.settings, "LLM_API_KEY", "")
    monkeypatch.setattr(llm.settings, "GEMINI_API_KEYS", "gemini-test-key")
    monkeypatch.setattr(llm.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm.settings, "GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setattr(llm.settings, "GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite,gemini-3.6-flash")
    result = Mock(return_value="Gemini answer")
    monkeypatch.setattr(llm, "call_gemini", result)
    return result


@pytest.mark.parametrize("error", [RuntimeError("429 quota"), RuntimeError("Connection error."), TimeoutError(), ApiKeyPoolUnavailable()])
def test_groq_failure_uses_explicit_gemini_model(monkeypatch, fallback, error):
    messages = [{"role": "user", "content": "Chính sách bảo hành?"}]
    monkeypatch.setattr(llm, "call_groq", Mock(side_effect=error))
    assert llm.call_llm(messages) == "Gemini answer"
    fallback.assert_called_once_with(messages, model="gemini-3.5-flash-lite")


def test_successful_groq_does_not_call_gemini(monkeypatch, fallback):
    monkeypatch.setattr(llm, "call_groq", Mock(return_value="Groq answer"))
    assert llm.call_llm([]) == "Groq answer"
    fallback.assert_not_called()


def test_invalid_payload_does_not_call_another_provider(monkeypatch, fallback):
    monkeypatch.setattr(llm, "call_groq", Mock(side_effect=ValueError("invalid payload")))
    with pytest.raises(ValueError, match="invalid payload"):
        llm.call_llm([])
    fallback.assert_not_called()


def test_disabled_fallback_preserves_original_error(monkeypatch, fallback):
    monkeypatch.setattr(llm.settings, "GEMINI_FALLBACK_MODEL", "")
    monkeypatch.setattr(llm, "call_groq", Mock(side_effect=RuntimeError("429 quota")))
    with pytest.raises(RuntimeError, match="429"):
        llm.call_llm([])
    fallback.assert_not_called()


def test_gemini_pool_never_uses_groq_key(monkeypatch, fallback):
    monkeypatch.setattr(llm.settings, "GEMINI_API_KEYS", "")
    monkeypatch.setattr(llm.settings, "EMBEDDING_PROVIDER", "local")
    assert llm._provider_pool("gemini").snapshot()["key_count"] == 0
    monkeypatch.setattr(llm.settings, "EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setattr(llm.settings, "EMBEDDING_API_KEYS", "")
    monkeypatch.setattr(llm.settings, "EMBEDDING_API_KEY", "")
    assert llm._provider_pool("gemini").snapshot()["key_count"] == 0
    monkeypatch.setattr(llm.settings, "EMBEDDING_API_KEYS", "embedding-gemini-key")
    assert llm._provider_pool("gemini").next_key() == "embedding-gemini-key"


@pytest.mark.parametrize("partial", [False, True])
def test_stream_fallback_only_before_first_text(monkeypatch, fallback, partial):
    async def groq(_messages):
        if partial:
            yield "Groq partial"
        raise RuntimeError("503 service unavailable")

    gemini_calls = []

    async def gemini(messages, *, model):
        gemini_calls.append((messages, model))
        yield "Gemini answer"

    monkeypatch.setattr(llm, "stream_groq", groq)
    monkeypatch.setattr(llm, "stream_gemini", gemini)
    output = []

    async def collect():
        async for part in llm.stream_llm([]):
            output.append(part)

    if partial:
        with pytest.raises(RuntimeError, match="503"):
            asyncio.run(collect())
        assert output == ["Groq partial"]
        assert gemini_calls == []
    else:
        asyncio.run(collect())
        assert output == ["Gemini answer"]
        assert gemini_calls == [([], "gemini-3.5-flash-lite")]


def test_vision_fallback_preserves_inline_image(monkeypatch, fallback):
    monkeypatch.setattr(llm, "call_groq_vision", Mock(side_effect=RuntimeError("503 service unavailable")))
    assert llm.call_llm_with_image([{"role": "user", "content": "Đây là gì?"}], b"image", "image/png") == "Gemini answer"
    messages = fallback.call_args.args[0]
    assert messages[0]["content"][1]["image_url"]["url"] == "data:image/png;base64,aW1hZ2U="


def test_failed_models_are_skipped_until_cooldown_expires(monkeypatch, fallback):
    now = [0.0]
    monkeypatch.setattr(llm, "_model_breaker", ProviderCircuitBreaker(
        failure_threshold=1, recovery_timeout=60, clock=lambda: now[0],
    ))
    groq = Mock(side_effect=RuntimeError("429 quota"))
    monkeypatch.setattr(llm, "call_groq", groq)

    def gemini(_messages, *, model):
        if model == "gemini-3.5-flash-lite":
            raise RuntimeError("429 model quota")
        return model

    fallback.side_effect = gemini
    assert llm.call_llm([]) == "gemini-3.1-flash-lite"
    assert llm.call_llm([]) == "gemini-3.1-flash-lite"
    assert groq.call_count == 1
    assert [c.kwargs["model"] for c in fallback.call_args_list] == [
        "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.1-flash-lite",
    ]
    now[0] = 61
    assert llm.call_llm([]) == "gemini-3.1-flash-lite"
    assert groq.call_count == 2


def test_fallback_models_are_deduplicated_and_bounded(monkeypatch, fallback):
    monkeypatch.setattr(llm.settings, "GEMINI_FALLBACK_MODELS", "models/gemini-3.5-flash-lite, gemini-3.1-flash-lite,gemini-3.6-flash,extra-model")
    assert [model for provider, model in llm._groq_model_routes() if provider == "gemini"] == [
        "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash",
    ]


def test_all_models_exhausted_returns_last_failure(monkeypatch, fallback):
    monkeypatch.setattr(llm, "call_groq", Mock(side_effect=RuntimeError("503 Groq unavailable")))
    fallback.side_effect = RuntimeError("429 Gemini quota")
    with pytest.raises(RuntimeError, match="429 Gemini quota"):
        llm.call_llm([])
    assert fallback.call_count == 3


def test_model_quota_does_not_cooldown_sibling_model_keys(monkeypatch, fallback):
    from app.services.api_key_pool import ApiKeyPool

    llm._pool_for.cache_clear()
    pool_a = llm._provider_pool("gemini", "model-a")
    pool_b = llm._provider_pool("gemini", "model-b")
    assert pool_a is not pool_b
    pool_a.report_failure(pool_a.next_key(), RuntimeError("429 model quota"))
    assert pool_a.snapshot()["available_count"] == 0
    assert pool_b.snapshot()["available_count"] == 1
    breaker = ProviderCircuitBreaker(failure_threshold=1)
    with pytest.raises(RuntimeError, match="429"):
        llm.call_with_key_rotation(
            ApiKeyPool(["key-a"]), lambda key: (_ for _ in ()).throw(RuntimeError("429")),
            provider="gemini", failure_scope="gemini:model-a", circuit_breaker=breaker,
        )
    assert llm.call_with_key_rotation(
        pool_b, lambda key: "ok", provider="gemini", failure_scope="gemini:model-b", circuit_breaker=breaker,
    ) == "ok"


@pytest.mark.parametrize("partial", [False, True])
def test_stream_can_move_to_second_gemini_only_before_any_text(monkeypatch, fallback, partial):
    async def groq(messages):
        raise RuntimeError("503 unavailable")
        yield

    seen = []

    async def gemini(messages, *, model):
        seen.append(model)
        if model == "gemini-3.5-flash-lite":
            if partial:
                yield "partial"
            raise RuntimeError("429 quota")
        yield "answer"

    monkeypatch.setattr(llm, "stream_groq", groq)
    monkeypatch.setattr(llm, "stream_gemini", gemini)
    output = []

    async def collect():
        async for part in llm.stream_llm([]):
            output.append(part)

    if partial:
        with pytest.raises(RuntimeError, match="429"):
            asyncio.run(collect())
        assert output == ["partial"]
        assert seen == ["gemini-3.5-flash-lite"]
    else:
        asyncio.run(collect())
        assert output == ["answer"]
        assert seen == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
