from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.provider_circuit_breaker import ProviderCircuitBreaker, ProviderCircuitOpen


def test_half_open_allows_only_one_probe_until_it_completes():
    now = [10.0]
    breaker = ProviderCircuitBreaker(failure_threshold=1, recovery_timeout=5, clock=lambda: now[0])
    breaker.record_failure("groq:test-model")
    now[0] = 16.0

    breaker.before_call("groq:test-model")
    assert breaker.state("groq:test-model") == "half_open"
    with pytest.raises(ProviderCircuitOpen):
        breaker.before_call("groq:test-model")

    breaker.record_success("groq:test-model")
    breaker.before_call("groq:test-model")
    assert breaker.state("groq:test-model") == "closed"


def test_half_open_probe_failure_reopens_circuit_and_starts_new_cooldown():
    now = [10.0]
    breaker = ProviderCircuitBreaker(failure_threshold=1, recovery_timeout=5, clock=lambda: now[0])
    breaker.record_failure("gemini:test-model")
    now[0] = 16.0
    breaker.before_call("gemini:test-model")
    breaker.record_failure("gemini:test-model")

    assert breaker.state("gemini:test-model") == "open"
    with pytest.raises(ProviderCircuitOpen):
        breaker.before_call("gemini:test-model")
    now[0] = 22.0
    breaker.before_call("gemini:test-model")
    assert breaker.state("gemini:test-model") == "half_open"


def test_concurrent_half_open_calls_are_single_flight():
    now = [0.0]
    breaker = ProviderCircuitBreaker(failure_threshold=1, recovery_timeout=1, clock=lambda: now[0])
    breaker.record_failure("groq:concurrent")
    now[0] = 2.0

    def probe():
        try:
            breaker.before_call("groq:concurrent")
            return "admitted"
        except ProviderCircuitOpen:
            return "blocked"

    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(lambda _index: probe(), range(48)))

    assert outcomes.count("admitted") == 1
    assert outcomes.count("blocked") == 47
