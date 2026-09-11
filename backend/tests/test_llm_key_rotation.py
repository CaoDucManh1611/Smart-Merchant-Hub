import unittest

from app.rag.llm_caller import _call_with_key_rotation
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

    def test_retryable_failure_walks_the_full_five_key_pool(self):
        pool = ApiKeyPool(["key-a", "key-b", "key-c", "key-d", "key-e"])
        seen = []

        def operation(key):
            seen.append(key)
            if key != "key-e":
                raise RuntimeError("HTTP 429 rate limit")
            return "ok"

        self.assertEqual("ok", _call_with_key_rotation(pool, operation))
        self.assertEqual(["key-a", "key-b", "key-c", "key-d", "key-e"], seen)


if __name__ == "__main__":
    unittest.main()
