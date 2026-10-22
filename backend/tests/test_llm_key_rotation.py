import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from app.rag.llm_caller import _call_with_key_rotation, stream_groq
from app.services.api_key_pool import ApiKeyPool


class LlmKeyRotationTests(unittest.TestCase):
    def test_retryable_provider_failure_uses_the_next_key(self):
        pool = ApiKeyPool(["key-a", "key-b"])
        seen = []

        def operation(key):
            seen.append(key)
            if key == "key-a":
                raise RuntimeError("HTTP 429 rate limit")
            return "ok"

        self.assertEqual("ok", _call_with_key_rotation(pool, operation))
        self.assertEqual(["key-a", "key-b"], seen)

    def test_non_retryable_error_is_not_replayed(self):
        pool = ApiKeyPool(["key-a", "key-b"])
        seen = []

        def operation(key):
            seen.append(key)
            raise RuntimeError("invalid request payload")

        with self.assertRaisesRegex(RuntimeError, "invalid request"):
            _call_with_key_rotation(pool, operation)
        self.assertEqual(["key-a"], seen)

    def test_retryable_failure_stops_after_three_keys(self):
        pool = ApiKeyPool(["key-a", "key-b", "key-c", "key-d", "key-e"])
        seen = []

        def operation(key):
            seen.append(key)
            raise RuntimeError("HTTP 429 rate limit")

        with self.assertRaisesRegex(RuntimeError, "429"):
            _call_with_key_rotation(pool, operation, provider="test-bounded")
        self.assertEqual(["key-a", "key-b", "key-c"], seen)

    def test_stream_does_not_retry_after_emitting_partial_text(self):
        pool = ApiKeyPool(["key-a", "key-b"])
        calls = []

        class PartialThenFailure:
            def __iter__(self):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="part"))])
                raise RuntimeError("HTTP 429 quota")

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_kwargs: PartialThenFailure(),
        )))

        async def collect():
            result = []
            async for part in stream_groq([]):
                result.append(part)
            return result

        def make_client(key):
            calls.append(key)
            return client

        with patch("app.rag.llm_caller._provider_pool", return_value=pool), \
             patch("app.rag.llm_caller._groq_client", side_effect=make_client):
            with self.assertRaisesRegex(RuntimeError, "429"):
                asyncio.run(collect())

        self.assertEqual(["key-a"], calls)


if __name__ == "__main__":
    unittest.main()
