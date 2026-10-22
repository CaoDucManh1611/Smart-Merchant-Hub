import unittest
from contextlib import ExitStack

from app.services.api_key_pool import ApiKeyPool, ApiKeyPoolUnavailable, provider_request_slot
from app.services.provider_circuit_breaker import ProviderCircuitBreaker
from app.services.api_key_pool import call_with_key_rotation


class ApiKeyPoolTests(unittest.TestCase):
    def test_round_robin_uses_each_key_without_exposing_values(self):
        pool = ApiKeyPool(["key-a", "key-b", "key-c", "key-d", "key-e"])

        selected = [pool.next_key() for _ in range(7)]

        self.assertEqual(
            ["key-a", "key-b", "key-c", "key-d", "key-e", "key-a", "key-b"],
            selected,
        )
        snapshot = pool.snapshot()
        self.assertEqual(5, snapshot["key_count"])
        self.assertNotIn("key-a", str(snapshot))
        self.assertNotIn("key-e", str(snapshot))

    def test_failed_key_is_skipped_during_cooldown(self):
        now = [100.0]
        pool = ApiKeyPool(["key-a", "key-b", "key-c"], cooldown_seconds=30, clock=lambda: now[0])

        self.assertEqual("key-a", pool.next_key())
        pool.report_failure("key-a", RuntimeError("HTTP 429 rate limit"))
        self.assertEqual("key-b", pool.next_key())
        self.assertEqual("key-c", pool.next_key())
        self.assertEqual("key-b", pool.next_key())

        now[0] = 131.0
        self.assertEqual("key-c", pool.next_key())
        self.assertEqual("key-a", pool.next_key())

    def test_non_transient_failure_does_not_cool_key(self):
        pool = ApiKeyPool(["key-a", "key-b"], cooldown_seconds=30)

        pool.report_failure("key-a", RuntimeError("invalid request payload"))

        self.assertEqual("key-a", pool.next_key())

    def test_empty_or_excluded_pool_is_explicit(self):
        pool = ApiKeyPool([])

        with self.assertRaises(ApiKeyPoolUnavailable):
            pool.next_key()

        pool = ApiKeyPool(["key-a"])
        with self.assertRaises(ApiKeyPoolUnavailable):
            pool.next_key(exclude={"key-a"})

    def test_provider_concurrency_limit_fails_fast_when_all_slots_are_busy(self):
        provider = "test-provider-capacity"
        with ExitStack() as stack:
            for _ in range(4):
                stack.enter_context(provider_request_slot(provider, timeout_seconds=0))
            with self.assertRaises(ApiKeyPoolUnavailable):
                with provider_request_slot(provider, timeout_seconds=0):
                    self.fail("A fifth concurrent request must not enter")

    def test_circuit_breaker_state_is_separate_per_provider(self):
        breaker = ProviderCircuitBreaker(failure_threshold=1)
        broken = ApiKeyPool(["broken"])
        with self.assertRaisesRegex(RuntimeError, "429"):
            call_with_key_rotation(
                broken,
                lambda _key: (_ for _ in ()).throw(RuntimeError("HTTP 429 quota")),
                provider="groq",
                circuit_breaker=breaker,
            )

        self.assertEqual("ok", call_with_key_rotation(
            ApiKeyPool(["healthy"]), lambda _key: "ok", provider="gemini", circuit_breaker=breaker,
        ))
        self.assertEqual("open", breaker.state("groq"))
        self.assertEqual("closed", breaker.state("gemini"))


if __name__ == "__main__":
    unittest.main()
