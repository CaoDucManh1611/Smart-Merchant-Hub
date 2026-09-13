import sys
import types

from app.core.config import settings
from app.rag.llm_caller import _call_gemini_once


def test_gemini_generation_uses_supported_google_genai_client(monkeypatch):
    calls = []
    fake_api = types.ModuleType("google.genai")
    fake_types = types.ModuleType("google.genai.types")

    class Part:
        @staticmethod
        def from_text(*, text):
            return {"text": text}

    class Content:
        def __init__(self, *, role, parts):
            self.role = role
            self.parts = parts

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    fake_types.Part = Part
    fake_types.Content = Content
    fake_types.GenerateContentConfig = GenerateContentConfig

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(text="Xin chào")

    class Client:
        def __init__(self, **kwargs):
            calls.append({"client": kwargs})
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
    monkeypatch.setattr(settings, "LLM_MODEL", "models/gemini-test")

    result = _call_gemini_once(
        [
            {"role": "system", "content": "Trả lời ngắn gọn"},
            {"role": "user", "content": "Xin chào"},
        ],
        "test-key",
    )

    assert result == "Xin chào"
    assert calls[0] == {"client": {"api_key": "test-key"}}
    assert calls[1]["model"] == "gemini-test"
    assert calls[1]["config"].system_instruction == "Trả lời ngắn gọn"
    assert calls[1]["contents"][0].role == "user"
