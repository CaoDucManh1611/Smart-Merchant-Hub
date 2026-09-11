"""
LLM Caller – gọi LLM API để sinh câu trả lời.

Hỗ trợ:
- Groq (default, OpenAI-compatible API)
- Google Gemini
- OpenAI GPT
- Streaming response
"""

import logging
from collections.abc import AsyncGenerator
from functools import lru_cache

from app.core.config import settings
from app.services.api_key_pool import (
    ApiKeyPool,
    ApiKeyPoolUnavailable,
    call_with_key_rotation,
    is_retryable_provider_error,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=12)
def _pool_for(scope: str, keys: tuple[str, ...], cooldown_seconds: int) -> ApiKeyPool:
    return ApiKeyPool(list(keys), cooldown_seconds=cooldown_seconds)


def _provider_pool(provider: str) -> ApiKeyPool:
    keys = settings.groq_api_keys if provider == "groq" else settings.llm_api_keys
    return _pool_for(provider, tuple(keys), settings.API_KEY_COOLDOWN_SECONDS)


def _embedding_pool() -> ApiKeyPool:
    return _pool_for(
        "embedding",
        tuple(settings.embedding_api_keys),
        settings.API_KEY_COOLDOWN_SECONDS,
    )


def _call_with_key_rotation(pool: ApiKeyPool, operation):
    return call_with_key_rotation(pool, operation)


# =========================================================
# GROQ
# =========================================================


def _groq_client(api_key: str | None = None):
    """Tạo OpenAI-compatible client trỏ tới GroqCloud."""
    from openai import OpenAI

    if not api_key and not settings.groq_api_keys:
        raise ValueError("GROQ_API_KEY chưa được cấu hình trong backend/.env.")

    return OpenAI(
        api_key=api_key or settings.groq_api_keys[0],
        base_url="https://api.groq.com/openai/v1",
    )


def call_groq(messages: list[dict]) -> str:
    """Gọi Groq Chat Completions API (non-streaming)."""
    return _call_with_key_rotation(
        _provider_pool("groq"),
        lambda key: _groq_client(key).chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=0.3,
        ).choices[0].message.content or "",
    )


async def stream_groq(
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Gọi Groq Chat Completions API với streaming."""
    pool = _provider_pool("groq")
    attempted: set[str] = set()
    max_attempts = pool.snapshot()["key_count"]
    if max_attempts <= 0:
        raise ApiKeyPoolUnavailable("Không có API key cho provider đang chọn.")
    for attempt in range(max_attempts):
        key = pool.next_key(exclude=attempted)
        attempted.add(key)
        emitted = False
        try:
            response = _groq_client(key).chat.completions.create(
                model=settings.LLM_MODEL,
                messages=messages,
                temperature=0.3,
                stream=True,
            )
            for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    emitted = True
                    yield delta.content
            return
        except Exception as error:
            pool.report_failure(key, error)
            if emitted or not is_retryable_provider_error(error) or attempt + 1 >= max_attempts:
                raise


# =========================================================
# GEMINI
# =========================================================


def _messages_to_gemini_format(
    messages: list[dict],
) -> tuple[str, list[dict]]:
    """
    Chuyển messages format (OpenAI-style) sang Gemini format.

    Returns:
        (system_instruction, history_contents)
    """
    system_instruction = ""
    history = []

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "system":
            system_instruction = content
        elif role == "user":
            history.append({"role": "user", "parts": [content]})
        elif role == "assistant":
            history.append({"role": "model", "parts": [content]})

    return system_instruction, history


def _call_gemini_once(messages: list[dict], api_key: str) -> str:
    """Gọi một lần Gemini API với key đã được chọn."""
    import google.generativeai as genai

    genai.configure(api_key=api_key)

    system_instruction, history = _messages_to_gemini_format(
        messages
    )

    model = genai.GenerativeModel(
        model_name=settings.LLM_MODEL,
        system_instruction=system_instruction or None,
    )

    # Phần cuối cùng trong history là user message
    if not history:
        return ""

    # Tạo chat và gửi tin nhắn
    user_message = history[-1]
    chat_history = history[:-1] if len(history) > 1 else []

    chat = model.start_chat(history=chat_history)
    response = chat.send_message(user_message["parts"][0])

    return response.text


def call_gemini(messages: list[dict]) -> str:
    """Gọi Gemini API (non-streaming) với pool key."""
    return _call_with_key_rotation(
        _provider_pool("gemini"),
        lambda key: _call_gemini_once(messages, key),
    )


async def stream_gemini(
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Gọi Gemini API với streaming."""
    import google.generativeai as genai

    pool = _provider_pool("gemini")
    attempted: set[str] = set()
    max_attempts = pool.snapshot()["key_count"]
    if max_attempts <= 0:
        raise ApiKeyPoolUnavailable("Không có API key cho provider đang chọn.")
    for attempt in range(max_attempts):
        key = pool.next_key(exclude=attempted)
        attempted.add(key)
        emitted = False
        try:
            genai.configure(api_key=key)
            system_instruction, history = _messages_to_gemini_format(messages)
            model = genai.GenerativeModel(
                model_name=settings.LLM_MODEL,
                system_instruction=system_instruction or None,
            )
            if not history:
                return
            user_message = history[-1]
            chat = model.start_chat(history=history[:-1] if len(history) > 1 else [])
            response = chat.send_message(user_message["parts"][0], stream=True)
            for chunk in response:
                if chunk.text:
                    emitted = True
                    yield chunk.text
            return
        except Exception as error:
            pool.report_failure(key, error)
            if emitted or not is_retryable_provider_error(error) or attempt + 1 >= max_attempts:
                raise


# =========================================================
# OPENAI
# =========================================================


def call_openai(messages: list[dict]) -> str:
    """Gọi OpenAI API (non-streaming) với pool key."""
    from openai import OpenAI

    return _call_with_key_rotation(
        _provider_pool("openai"),
        lambda key: OpenAI(api_key=key).chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=0.3,
        ).choices[0].message.content or "",
    )


async def stream_openai(
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Gọi OpenAI API với streaming."""
    from openai import OpenAI

    pool = _provider_pool("openai")
    attempted: set[str] = set()
    max_attempts = pool.snapshot()["key_count"]
    if max_attempts <= 0:
        raise ApiKeyPoolUnavailable("Không có API key cho provider đang chọn.")
    for attempt in range(max_attempts):
        key = pool.next_key(exclude=attempted)
        attempted.add(key)
        emitted = False
        try:
            response = OpenAI(api_key=key).chat.completions.create(
                model=settings.LLM_MODEL,
                messages=messages,
                temperature=0.3,
                stream=True,
            )
            for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    emitted = True
                    yield delta.content
            return
        except Exception as error:
            pool.report_failure(key, error)
            if emitted or not is_retryable_provider_error(error) or attempt + 1 >= max_attempts:
                raise


# =========================================================
# PUBLIC API
# =========================================================


def call_llm(messages: list[dict]) -> str:
    """
    Gọi LLM (non-streaming). Tự chọn provider theo config.

    Args:
        messages: [{role, content}, ...]

    Returns:
        Response text
    """
    provider = settings.LLM_PROVIDER

    logger.info(
        "Calling LLM: %s/%s",
        provider,
        settings.LLM_MODEL,
    )

    if provider == "groq":
        return call_groq(messages)
    elif provider == "gemini":
        return call_gemini(messages)
    elif provider == "openai":
        return call_openai(messages)
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Supported: groq, gemini, openai"
        )


async def stream_llm(
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """
    Gọi LLM với streaming response. Tự chọn provider theo config.

    Yields:
        Từng phần text response
    """
    provider = settings.LLM_PROVIDER

    logger.info(
        "Streaming LLM: %s/%s",
        provider,
        settings.LLM_MODEL,
    )

    if provider == "groq":
        async for chunk in stream_groq(messages):
            yield chunk
    elif provider == "gemini":
        async for chunk in stream_gemini(messages):
            yield chunk
    elif provider == "openai":
        async for chunk in stream_openai(messages):
            yield chunk
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Supported: groq, gemini, openai"
        )
