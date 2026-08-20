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

import google.generativeai as genai

from app.core.config import settings

logger = logging.getLogger(__name__)


# =========================================================
# GROQ
# =========================================================


def _groq_client():
    """Tạo OpenAI-compatible client trỏ tới GroqCloud."""
    from openai import OpenAI

    if not settings.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY chưa được cấu hình trong backend/.env.")

    return OpenAI(
        api_key=settings.GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
    )


def call_groq(messages: list[dict]) -> str:
    """Gọi Groq Chat Completions API (non-streaming)."""
    response = _groq_client().chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.3,
    )
    return response.choices[0].message.content or ""


async def stream_groq(
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Gọi Groq Chat Completions API với streaming."""
    response = _groq_client().chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.3,
        stream=True,
    )

    for chunk in response:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


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


def call_gemini(messages: list[dict]) -> str:
    """Gọi Gemini API (non-streaming)."""
    genai.configure(api_key=settings.LLM_API_KEY)

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


async def stream_gemini(
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Gọi Gemini API với streaming."""
    genai.configure(api_key=settings.LLM_API_KEY)

    system_instruction, history = _messages_to_gemini_format(
        messages
    )

    model = genai.GenerativeModel(
        model_name=settings.LLM_MODEL,
        system_instruction=system_instruction or None,
    )

    if not history:
        return

    user_message = history[-1]
    chat_history = history[:-1] if len(history) > 1 else []

    chat = model.start_chat(history=chat_history)
    response = chat.send_message(
        user_message["parts"][0],
        stream=True,
    )

    for chunk in response:
        if chunk.text:
            yield chunk.text


# =========================================================
# OPENAI
# =========================================================


def call_openai(messages: list[dict]) -> str:
    """Gọi OpenAI API (non-streaming)."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.LLM_API_KEY)

    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.3,
    )

    return response.choices[0].message.content or ""


async def stream_openai(
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Gọi OpenAI API với streaming."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.LLM_API_KEY)

    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.3,
        stream=True,
    )

    for chunk in response:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


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
