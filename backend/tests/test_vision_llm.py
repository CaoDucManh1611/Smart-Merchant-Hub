import base64
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import settings
from app.rag import llm_caller


def test_groq_image_turn_uses_vision_model_and_inline_image():
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Ảnh có một chiếc áo màu hồng."))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    messages = [
        {"role": "system", "content": "Không đoán tồn kho."},
        {"role": "user", "content": "Khách gửi ảnh, xem giúp."},
    ]
    with patch.object(settings, "LLM_PROVIDER", "groq"), \
         patch.object(settings, "GROQ_VISION_MODEL", "qwen/qwen3.8-27b"), \
         patch.object(llm_caller, "_groq_client", return_value=client), \
         patch.object(llm_caller, "_call_with_key_rotation", side_effect=lambda _pool, call: call("test-key")):
        answer = llm_caller.call_llm_with_image(messages, b"image-bytes", "image/jpeg")

    assert answer == "Ảnh có một chiếc áo màu hồng."
    assert calls[0]["model"] == "qwen/qwen3.8-27b"
    content = calls[0]["messages"][-1]["content"]
    assert content[0]["text"] == "Khách gửi ảnh, xem giúp."
    assert content[1]["image_url"]["url"] == (
        "data:image/jpeg;base64," + base64.b64encode(b"image-bytes").decode("ascii")
    )
