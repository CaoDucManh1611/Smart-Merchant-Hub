"""Offline transport/budget checks; runnable with pytest --noconftest (no DB)."""

import asyncio
import json
from contextlib import contextmanager
from copy import deepcopy
import socket
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from pydantic import BaseModel, ConfigDict

from app.rag import llm_caller as llm
from app.rag import turn_budget as tb
from app.services import api_key_pool as keys
from app.services.provider_circuit_breaker import ProviderCircuitBreaker, ProviderCircuitOpen


MESSAGES = [{"role": "system", "content": "Only current shop evidence."}, {"role": "user", "content": "Question"}]
SCHEMA = {
    "type": "object", "properties": {"mode": {"type": "string", "enum": ["answer", "chat"]}},
    "required": ["mode"], "additionalProperties": False,
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original_connect = socket.socket.connect
    def forbidden(*args, **kwargs):
        # Windows asyncio uses a loopback socketpair for its wakeup pipe.
        caller = sys._getframe(1).f_code
        if caller.co_name == "_fallback_socketpair" and caller.co_filename == socket.__file__:
            return original_connect(*args, **kwargs)
        raise AssertionError("Network is forbidden in LLM unit tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(llm, "_model_breaker", ProviderCircuitBreaker(failure_threshold=1))
    monkeypatch.setattr(keys, "_provider_breaker", ProviderCircuitBreaker(failure_threshold=100))
    for name, value in {
        "LLM_PROVIDER": "groq", "LLM_MODEL": "openai/gpt-oss-20b",
        "GROQ_API_KEYS": "g-a,g-b,g-c", "GROQ_API_KEY": "",
        "LLM_API_KEYS": "o-a,o-b,o-c", "LLM_API_KEY": "",
        "GEMINI_API_KEYS": "m-a,m-b,m-c", "GEMINI_API_KEY": "",
        "GEMINI_FALLBACK_MODEL": "gemini-test-a", "GEMINI_FALLBACK_MODELS": "gemini-test-b,gemini-test-c",
    }.items():
        monkeypatch.setattr(llm.settings, name, value)
    llm._pool_for.cache_clear()
    yield
    llm._pool_for.cache_clear()


@pytest.fixture
def now(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(tb.time, "monotonic", lambda: clock[0])
    return clock


def openai_fake(monkeypatch, operation, *, provider="groq"):
    create = Mock(side_effect=operation)
    client = NS(chat=NS(completions=NS(create=create)))
    if provider == "groq":
        constructor = Mock(return_value=client)
        monkeypatch.setattr(llm, "_groq_client", constructor)
    else:
        import openai
        constructor = Mock(return_value=client)
        monkeypatch.setattr(openai, "OpenAI", constructor)
    return constructor, create


def response(text='{"mode":"answer"}', usage=None):
    return NS(choices=[NS(message=NS(content=text))], usage=usage)


def gemini_fake(monkeypatch, operation):
    from google import genai
    generate = Mock(side_effect=operation)
    class Client:
        def __init__(self, **kwargs):
            self.models = NS(generate_content=generate, generate_content_stream=generate)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
    constructor = Mock(side_effect=Client)
    monkeypatch.setattr(genai, "Client", constructor)
    return constructor, generate


def test_defaults_reset_and_retrieval_timeout(now):
    assert tb.remaining_seconds(8.0) == 8.0
    with tb.turn_budget() as budget:
        assert budget.snapshot()["max_calls"] == 4
        assert budget.snapshot()["max_attempts"] == 6
        assert budget.snapshot()["max_provider_switches"] == 1
        now[0] += 26
        assert tb.remaining_seconds(8.0) == 4
        now[0] += 4
        with pytest.raises(tb.TurnBudgetExceeded, match="deadline"):
            tb.remaining_seconds(8.0)
        assert budget.snapshot()["remaining_seconds"] == 0
    assert tb.current_budget() is None


@pytest.mark.parametrize("kwargs", [{"timeout_seconds": 0}, {"timeout_seconds": float("inf")}, {"max_calls": -1}, {"max_attempts": 1.5}, {"max_provider_switches": True}])
def test_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        with tb.turn_budget(**kwargs):
            pass


def test_nested_budget_cannot_replenish_parent(now):
    with tb.turn_budget(max_calls=1, max_attempts=1) as parent:
        with tb.turn_budget(timeout_seconds=100, max_calls=99, max_attempts=99) as child:
            assert child.deadline == parent.deadline
            child.start_call()
            with tb.physical_attempt("groq", "actual-model"):
                pass
        assert tb.current_budget() is parent
        with pytest.raises(tb.TurnBudgetExceeded, match="max_calls"):
            parent.start_call()
        assert parent.snapshot()["attempts"] == 1


def test_one_logical_call_across_provider_wrappers(monkeypatch):
    _, create = openai_fake(monkeypatch, lambda **kwargs: response("ok"))
    with tb.turn_budget(max_calls=1) as budget:
        assert llm.call_llm(MESSAGES) == "ok"
        with pytest.raises(tb.TurnBudgetExceeded, match="max_calls"):
            llm.call_llm(MESSAGES)
        assert budget.snapshot()["calls"] == budget.snapshot()["attempts"] == 1
    assert create.call_count == 1


def test_rotation_and_all_fallback_models_share_attempt_limit(monkeypatch):
    seen = []
    def fail(**kwargs):
        seen.append(kwargs["model"])
        raise RuntimeError("HTTP 429 quota")
    openai_fake(monkeypatch, fail)
    gemini_fake(monkeypatch, fail)
    with tb.turn_budget(max_attempts=4) as budget:
        with pytest.raises(RuntimeError, match="429 quota"):
            llm.call_llm(MESSAGES)
        snap = budget.snapshot()
    assert len(seen) == snap["attempts"] == 4
    assert seen == ["openai/gpt-oss-20b", "gemini-test-a", "gemini-test-b", "gemini-test-c"]
    assert snap["calls"] == 1 and snap["provider_switches"] == 1
    assert llm._model_breaker.state("gemini:gemini-test-a") == "open"
    assert all(r["usage"] is None and r["outcome"] == "error" for r in snap["attempt_records"])


def test_switch_limit_preserves_keys_and_circuits(monkeypatch):
    openai_fake(monkeypatch, lambda **kwargs: (_ for _ in ()).throw(RuntimeError("429 quota")))
    _, gemini = gemini_fake(monkeypatch, lambda **kwargs: NS(text="ok"))
    with tb.turn_budget(max_provider_switches=0) as budget:
        with pytest.raises(tb.TurnBudgetExceeded, match="max_provider_switches"):
            llm.call_llm(MESSAGES)
        assert budget.snapshot()["attempts"] == 1
        assert budget.snapshot()["provider_switches"] == 0
    gemini.assert_not_called()
    assert llm._provider_pool("gemini", "gemini-test-a").snapshot()["available_count"] == 3
    assert llm._model_breaker.state("gemini:gemini-test-a") == "closed"


def test_provider_switch_counts_across_logical_calls(monkeypatch):
    openai_fake(monkeypatch, lambda **kwargs: response("ok"))
    gemini_fake(monkeypatch, lambda **kwargs: NS(text="ok"))
    with tb.turn_budget() as budget:
        llm.call_groq(MESSAGES)
        llm.call_gemini(MESSAGES, model="actual-a")
        llm.call_gemini(MESSAGES, model="actual-b")
        with pytest.raises(tb.TurnBudgetExceeded, match="max_provider_switches"):
            llm.call_groq(MESSAGES)
        assert budget.snapshot()["attempts"] == 3


def test_timeout_clamps_after_slot_wait_and_rejects_late_success(monkeypatch, now):
    seen = []
    @contextmanager
    def slot(provider, *, timeout_seconds):
        assert timeout_seconds == 5
        now[0] += 2
        yield
    monkeypatch.setattr(keys, "provider_request_slot", slot)
    def late(**kwargs):
        seen.append(kwargs["timeout"])
        now[0] += 4
        return response("late")
    openai_fake(monkeypatch, late)
    with tb.turn_budget(timeout_seconds=5) as budget:
        with pytest.raises(tb.TurnBudgetExceeded, match="deadline"):
            llm.call_llm(MESSAGES)
        snap = budget.snapshot()
    assert seen == [3]
    assert snap["attempt_records"][0]["latency_ms"] == 4000
    assert snap["attempt_records"][0]["error_type"] == "TurnBudgetExceeded"
    assert llm._provider_pool("groq").snapshot()["available_count"] == 3


@pytest.mark.parametrize("provider", ["groq", "openai", "gemini"])
def test_sdk_timeouts_and_real_usage(monkeypatch, now, provider):
    monkeypatch.setattr(llm.settings, "LLM_PROVIDER", provider)
    def succeed(**kwargs):
        now[0] += .25
        if provider == "gemini":
            return NS(text="ok", usage_metadata=NS(prompt_token_count=9, candidates_token_count=0, total_token_count=9))
        return response("ok", NS(prompt_tokens=9, completion_tokens=0, total_tokens=9))
    constructor, create = gemini_fake(monkeypatch, succeed) if provider == "gemini" else openai_fake(monkeypatch, succeed, provider=provider)
    with tb.turn_budget(timeout_seconds=7) as budget:
        assert llm.call_llm(MESSAGES) == "ok"
        record = budget.snapshot()["attempt_records"][0]
        record["usage"]["prompt_tokens"] = 999
        record = budget.snapshot()["attempt_records"][0]
    assert record["model"] == "openai/gpt-oss-20b"
    assert record["latency_ms"] == 250
    assert record["usage"] == {"prompt_tokens": 9, "completion_tokens": 0, "total_tokens": 9, "thoughts_tokens": None}
    if provider == "gemini":
        assert constructor.call_args.kwargs["http_options"] == {"timeout": 7000, "retry_options": {"attempts": 1}}
    else:
        assert create.call_args.kwargs["timeout"] == 7
        if provider == "openai":
            assert constructor.call_args.kwargs["max_retries"] == 0


def test_no_budget_preserves_legacy_groq_payload(monkeypatch):
    _, create = openai_fake(monkeypatch, lambda **kwargs: response("legacy"))
    assert llm.call_llm(MESSAGES) == "legacy"
    assert "timeout" not in create.call_args.kwargs
    assert "response_format" not in create.call_args.kwargs


def test_native_structured_identity_schema_and_telemetry(monkeypatch, now):
    original = deepcopy(SCHEMA)
    _, create = openai_fake(monkeypatch, lambda **kwargs: response(usage=NS(prompt_tokens=10, completion_tokens=3, total_tokens=13)))
    with llm.capture_llm_trace() as trace:
        with tb.turn_budget() as budget:
            assert llm.call_structured(MESSAGES, SCHEMA, schema_name="turn_plan", model=llm.call_llm) == {"mode": "answer"}
            assert budget.snapshot()["calls"] == budget.snapshot()["attempts"] == 1
            assert budget.snapshot()["attempt_records"][0]["usage"]["total_tokens"] == 13
    payload = create.call_args.kwargs
    assert payload["response_format"] == {"type": "json_schema", "json_schema": {"name": "turn_plan", "strict": True, "schema": SCHEMA}}
    assert payload["messages"] is MESSAGES and SCHEMA == original
    assert trace[0]["provider"] == "groq"
    assert trace[0]["model"] == "openai/gpt-oss-20b"
    assert trace[0]["schema_name"] == "turn_plan"
    assert len(trace[0]["schema_fingerprint"]) == 64
    assert trace[0]["response_text"] == '{"mode":"answer"}'
    assert trace[0]["parse_status"] == trace[0]["validation_status"] == "passed"
    assert budget.snapshot()["attempt_records"][0]["schema_name"] == "turn_plan"
    assert budget.snapshot()["attempt_records"][0]["schema_fingerprint"] == trace[0]["schema_fingerprint"]


def test_structured_http_400_captures_schema_and_provider_error_without_key_rotation(monkeypatch):
    error = RuntimeError("synthetic bad request")
    error.status_code = 400
    error.code = "invalid_json_schema"
    error.param = "response_format"
    _, create = openai_fake(monkeypatch, lambda **_kwargs: (_ for _ in ()).throw(error))

    with llm.capture_llm_trace() as trace:
        with tb.turn_budget() as budget:
            with pytest.raises(RuntimeError, match="synthetic bad request"):
                llm.call_structured(MESSAGES, SCHEMA, schema_name="answer_contract")
            snapshot = budget.snapshot()

    assert create.call_count == 1
    attempt = snapshot["attempt_records"][0]
    assert attempt["status_code"] == 400
    assert attempt["provider_error_code"] == "invalid_json_schema"
    assert attempt["provider_error_param"] == "response_format"
    assert attempt["schema_name"] == "answer_contract"
    assert len(attempt["schema_fingerprint"]) == 64
    assert trace[0]["schema_name"] == "answer_contract"
    assert trace[0]["routes"][0]["status_code"] == 400
    assert snapshot["attempts"] == 1


def test_attempt_context_adds_only_safe_schema_metadata_to_attempt_record(now):
    with tb.turn_budget() as budget:
        with tb.attempt_context(
            llm_stage="structured_output",
            schema_name="shop_answer",
            schema_fingerprint="a" * 64,
        ):
            with tb.physical_attempt("groq", "openai/gpt-oss-20b"):
                pass
        record = budget.snapshot()["attempt_records"][0]

    assert record["llm_stage"] == "structured_output"
    assert record["schema_name"] == "shop_answer"
    assert record["schema_fingerprint"] == "a" * 64
    assert "messages" not in record and "prompt" not in record and "key" not in record


def test_structured_fallback_keeps_native_schema_on_gemini(monkeypatch):
    openai_fake(monkeypatch, lambda **kwargs: (_ for _ in ()).throw(RuntimeError("429 quota")))
    constructor, gemini = gemini_fake(monkeypatch, lambda **kwargs: NS(text='{"mode":"chat"}'))
    with tb.turn_budget() as budget:
        assert llm.call_structured(MESSAGES, SCHEMA) == {"mode": "chat"}
        snap = budget.snapshot()
    config = gemini.call_args.kwargs["config"]
    assert config.response_json_schema == SCHEMA
    assert config.response_mime_type == "application/json"
    assert config.system_instruction == MESSAGES[0]["content"]
    assert constructor.call_args.kwargs["http_options"]["retry_options"]["attempts"] == 1
    assert [r["model"] for r in snap["attempt_records"]] == ["openai/gpt-oss-20b", "gemini-test-a"]
    assert snap["calls"] == 1 and snap["provider_switches"] == 1


def test_injected_messages_only_callable_and_patched_symbol(monkeypatch):
    fake = Mock(return_value='{"mode":"chat"}')
    monkeypatch.setattr(llm, "call_llm", fake)
    with tb.turn_budget() as budget:
        assert llm.call_structured(MESSAGES, SCHEMA, model=fake) == {"mode": "chat"}
        assert budget.snapshot()["calls"] == 1
        assert budget.snapshot()["attempts"] == 0  # fake has no SDK transport
    fake.assert_called_once_with(MESSAGES)


@pytest.mark.parametrize("value", ['```json\n{"mode":"answer"}\n```', '{"mode":"invalid"}', '{}', '{"mode":"answer","extra":1}', '[]', 'null', '{"mode":NaN}', '{"mode":1}', '{'])
def test_invalid_output_is_rejected_without_repair(value):
    fake = Mock(return_value=value)
    with pytest.raises(llm.StructuredOutputError):
        llm.call_structured(MESSAGES, SCHEMA, model=fake)
    assert fake.call_count == 1


def test_invalid_native_output_does_not_fallback_or_cool_key(monkeypatch):
    _, create = openai_fake(monkeypatch, lambda **kwargs: response('{"mode":"bad"}'))
    _, gemini = gemini_fake(monkeypatch, lambda **kwargs: NS(text='{"mode":"chat"}'))
    with pytest.raises(llm.StructuredOutputError):
        llm.call_structured(MESSAGES, SCHEMA)
    assert create.call_count == 1
    gemini.assert_not_called()
    assert llm._provider_pool("groq").snapshot()["available_count"] == 3


def test_pydantic_validation_and_non_object_root():
    class Plan(BaseModel):
        model_config = ConfigDict(extra="forbid")
        count: int
    assert llm.call_structured(MESSAGES, Plan, model=lambda messages: '{"count":2}') == {"count": 2}
    with pytest.raises(llm.StructuredOutputError):
        llm.call_structured(MESSAGES, Plan, model=lambda messages: '{"count":"2"}')


@pytest.mark.parametrize("schema", [{"type": "invalid"}, {"$ref": "https://example.invalid/schema"}])
def test_bad_schema_fails_before_model(schema):
    fake = Mock()
    with pytest.raises(llm.StructuredOutputError):
        llm.call_structured(MESSAGES, schema, model=fake)
    fake.assert_not_called()


def test_unsupported_groq_never_uses_prompt_only_json(monkeypatch):
    monkeypatch.setattr(llm.settings, "LLM_MODEL", "unknown-model")
    monkeypatch.setattr(llm.settings, "GEMINI_FALLBACK_MODEL", "")
    _, create = openai_fake(monkeypatch, lambda **kwargs: response())
    with pytest.raises(llm.StructuredOutputUnsupported):
        llm.call_structured(MESSAGES, SCHEMA)
    create.assert_not_called()


def test_circuit_open_does_not_consume_physical_attempt(monkeypatch):
    llm._model_breaker.record_failure("groq:openai/gpt-oss-20b")
    _, gemini = gemini_fake(monkeypatch, lambda **kwargs: NS(text='{"mode":"chat"}'))
    with tb.turn_budget(max_attempts=1) as budget:
        assert llm.call_structured(MESSAGES, SCHEMA) == {"mode": "chat"}
        assert budget.snapshot()["attempts"] == 1
        assert budget.snapshot()["provider_switches"] == 0


def test_context_isolation_and_to_thread_propagation():
    async def run():
        async def worker():
            with tb.turn_budget(max_attempts=1) as budget:
                def operation():
                    with tb.physical_attempt("groq", "actual"):
                        pass
                await asyncio.to_thread(operation)
                return budget.snapshot()
        return await asyncio.gather(worker(), worker())
    snapshots = asyncio.run(run())
    assert [s["attempts"] for s in snapshots] == [1, 1]
    assert tb.current_budget() is None


def test_stream_budget_closes_response_and_does_not_retry_partial(monkeypatch, now):
    class Stream:
        closed = False
        def __iter__(self):
            yield NS(choices=[NS(delta=NS(content="first"))])
            now[0] += 10
            yield NS(choices=[NS(delta=NS(content="late"))])
        def close(self):
            self.closed = True
    stream = Stream()
    _, create = openai_fake(monkeypatch, lambda **kwargs: stream)
    output = []
    async def run():
        with tb.turn_budget(timeout_seconds=5) as budget:
            with pytest.raises(tb.TurnBudgetExceeded, match="deadline"):
                async for text in llm.stream_llm(MESSAGES):
                    output.append(text)
            return budget.snapshot()
    snap = asyncio.run(run())
    assert output == ["first"] and stream.closed
    assert create.call_count == snap["attempts"] == snap["calls"] == 1
    assert llm._provider_pool("groq").snapshot()["available_count"] == 3
    assert snap["attempt_records"][0]["error_type"] == "TurnBudgetExceeded"


def test_stream_yield_does_not_hide_consumer_logical_calls(monkeypatch):
    chunk = NS(choices=[NS(delta=NS(content="first"))])
    openai_fake(monkeypatch, lambda **kwargs: iter([chunk]) if kwargs.get("stream") else response("ok"))
    async def run():
        with tb.turn_budget(max_calls=1):
            stream = llm.stream_groq(MESSAGES)
            assert await anext(stream) == "first"
            with pytest.raises(tb.TurnBudgetExceeded, match="max_calls"):
                llm.call_llm(MESSAGES)
            await stream.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("failure", [TimeoutError("request timed out"), type("RateLimit", (RuntimeError,), {"status_code": 429})("429 quota")])
def test_failed_attempt_latency_and_error_usage(monkeypatch, now, failure):
    def fail(**kwargs):
        now[0] += 1
        raise failure
    openai_fake(monkeypatch, fail)
    with tb.turn_budget(max_attempts=1) as budget:
        with pytest.raises(tb.TurnBudgetExceeded, match="max_attempts"):
            llm.call_llm(MESSAGES)
        snap = budget.snapshot()
    record = snap["attempt_records"][0]
    assert record["latency_ms"] == 1000
    assert record["error_type"] == type(failure).__name__
    assert record["status_code"] == getattr(failure, "status_code", None)
    assert record["usage"] is None
    assert "g-a" not in json.dumps(snap)


def test_deadline_during_slot_wait_never_dispatches_sdk(monkeypatch, now):
    @contextmanager
    def slot(*args, **kwargs):
        now[0] += 31
        yield
    monkeypatch.setattr(keys, "provider_request_slot", slot)
    _, create = openai_fake(monkeypatch, lambda **kwargs: response())
    with tb.turn_budget() as budget:
        with pytest.raises(tb.TurnBudgetExceeded, match="deadline"):
            llm.call_llm(MESSAGES)
        assert budget.snapshot()["attempts"] == 0
    create.assert_not_called()


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_direct_provider_streams_share_limits_and_capture_reported_usage(monkeypatch, provider):
    if provider == "gemini":
        chunks = [NS(text="ok", usage_metadata=NS(prompt_token_count=4, candidates_token_count=2, total_token_count=6))]
        gemini_fake(monkeypatch, lambda **kwargs: iter(chunks))
        generator = llm.stream_gemini
    else:
        chunks = [NS(choices=[NS(delta=NS(content="ok"))], usage=NS(prompt_tokens=4, completion_tokens=2, total_tokens=6))]
        openai_fake(monkeypatch, lambda **kwargs: iter(chunks), provider="openai")
        generator = llm.stream_openai
    async def run():
        with tb.turn_budget() as budget:
            assert [text async for text in generator(MESSAGES)] == ["ok"]
            return budget.snapshot()
    snap = asyncio.run(run())
    assert snap["calls"] == snap["attempts"] == 1
    assert snap["attempt_records"][0]["outcome"] == "success"
    assert snap["attempt_records"][0]["usage"]["total_tokens"] == 6


def test_injected_wrapper_around_native_llm_does_not_double_count(monkeypatch):
    openai_fake(monkeypatch, lambda **kwargs: response())
    def counted_model(messages):
        return llm.call_llm(messages)
    with tb.turn_budget(max_calls=1) as budget:
        assert llm.call_structured(MESSAGES, SCHEMA, model=counted_model) == {"mode": "answer"}
        assert budget.snapshot()["calls"] == budget.snapshot()["attempts"] == 1


def test_gemini_embedding_request_is_counted_and_sdk_retries_are_disabled(monkeypatch):
    from app.rag import embedder
    from google import genai
    from google.genai import types

    calls = []
    response_value = NS(
        embeddings=[NS(values=[0.1, 0.2, 0.3])],
        usage_metadata=NS(prompt_token_count=5, total_token_count=5),
    )

    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.models = NS(embed_content=Mock(return_value=response_value))
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(genai, "Client", Client)
    monkeypatch.setattr(embedder.settings, "EMBEDDING_DIMENSION", 3)
    with tb.turn_budget(max_calls=0, max_attempts=1) as budget:
        assert embedder._gemini_embed_query_once(
            genai, types, "synthetic-key", "synthetic query", "gemini-test-embed",
        ) == [0.1, 0.2, 0.3]
        snapshot = budget.snapshot()

    assert snapshot["attempts"] == 1
    assert snapshot["attempt_records"][0]["usage"]["total_tokens"] == 5
    assert calls[0]["http_options"].retry_options.attempts == 1


def test_openai_embedding_budget_exhaustion_prevents_sdk_dispatch():
    from app.rag import embedder

    dispatches = []

    class Client:
        def __init__(self, **kwargs):
            dispatches.append(("constructed", kwargs))
            self.embeddings = NS(create=lambda **_kwargs: dispatches.append("request"))

    with tb.turn_budget(max_attempts=0):
        with pytest.raises(tb.TurnBudgetExceeded, match="max_attempts"):
            embedder._openai_embed_batch_once(Client, "synthetic-key", ["synthetic"], "embed-test")
    assert dispatches == []
