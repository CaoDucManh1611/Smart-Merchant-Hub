import logging
import math
import re
from functools import lru_cache
from collections.abc import Callable

from app.core.config import settings
from app.services.api_key_pool import ApiKeyPool, ApiKeyPoolUnavailable, call_with_key_rotation
from app.rag.turn_budget import current_budget, physical_attempt, remaining_seconds

logger = logging.getLogger(__name__)


def _gemini_retry_delay(error: Exception) -> int:
    """Đọc số giây retry Gemini trả về, có fallback an toàn."""
    match = re.search(
        r"retry_delay.*?seconds:\s*(\d+)",
        str(error),
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return max(1, int(match.group(1)) + 1)
    return 60


def embedding_retry_delay(error: Exception) -> int | None:
    """Return a safe retry delay for temporary provider throttling.

    Providers do not use one consistent error shape: Gemini commonly returns
    HTTP 429/``RESOURCE_EXHAUSTED`` with a ``retry_delay`` field, while other
    clients only include a quota/rate-limit phrase.  Persisting this signal on
    the document lets the UI tell an operator when a lexical-only index can be
    retried.  Non-transient failures return ``None``.
    """
    message = str(error).lower()
    transient_markers = (
        "429",
        "quota",
        "rate limit",
        "rate_limit",
        "resource_exhausted",
        "too many requests",
    )
    if not any(marker in message for marker in transient_markers):
        return None
    return _gemini_retry_delay(error)


def _embedding_api_key() -> str:
    """Return one embedding key, preserving the legacy single-key fallback."""
    try:
        return _embedding_pool().next_key()
    except ApiKeyPoolUnavailable as error:
        raise ValueError("EMBEDDING_API_KEY chưa được cấu hình trong backend/.env.") from error


@lru_cache(maxsize=4)
def _embedding_pool(keys: tuple[str, ...] | None = None, cooldown_seconds: int | None = None) -> ApiKeyPool:
    return ApiKeyPool(
        list(keys if keys is not None else settings.embedding_api_keys),
        cooldown_seconds=cooldown_seconds or settings.API_KEY_COOLDOWN_SECONDS,
    )


def _validate_vectors(
    vectors: list[list[float]],
    expected_count: int | None = None,
) -> list[list[float]]:
    """Validate provider output before vectors reach pgvector."""
    if expected_count is not None and len(vectors) != expected_count:
        raise ValueError(
            "Embedding provider returned an unexpected number of vectors: "
            f"expected {expected_count}, got {len(vectors)}."
        )

    expected_dimension = settings.EMBEDDING_DIMENSION
    for index, vector in enumerate(vectors):
        if len(vector) != expected_dimension:
            raise ValueError(
                "Embedding dimension mismatch at index "
                f"{index}: expected {expected_dimension}, got {len(vector)}. "
                "Check EMBEDDING_MODEL/EMBEDDING_DIMENSION and the DB vector column."
            )
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector):
            raise ValueError("Embedding provider returned a non-finite or non-numeric vector.")
    return vectors


def _embed_with_gemini(
    texts: list[str],
    model: str,
    progress_callback: Callable[[float], None] | None = None,
    *, task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Embed texts bằng Google Gemini API."""
    from google import genai
    from google.genai import types

    embeddings = []
    # Gemini hỗ trợ batch nhưng giới hạn ~100 texts/request
    batch_size = 100
    total_batches = max(1, (len(texts) + batch_size - 1) // batch_size)
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        # One bounded key-rotation pass; durable ingestion owns later retries.
        result = call_with_key_rotation(
            _embedding_pool(tuple(settings.embedding_api_keys), settings.API_KEY_COOLDOWN_SECONDS),
            lambda key: _gemini_embed_batch_once(genai, types, key, batch, model, task_type=task_type),
            provider="embedding",
        )
        embeddings.extend(result)
        if progress_callback is not None:
            progress_callback(min(1.0, (i + len(batch)) / len(texts)))

    return embeddings


def _gemini_embed_batch_once(genai, types, api_key: str, batch: list[str], model: str, *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    options = {}
    if current_budget():
        options["http_options"] = {
            "timeout": max(1, int(remaining_seconds(30.0) * 1000)),
            "retry_options": {"attempts": 1},
        }
    with physical_attempt("gemini", model):
        with genai.Client(api_key=api_key, **options) as client:
            response = client.models.embed_content(
                model=model.removeprefix("models/"),
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=settings.EMBEDDING_DIMENSION,
                ),
            )
        _record_embedding_usage(response, "gemini", model)
    return [list(item.values) for item in response.embeddings or []]


def _embed_query_with_gemini(
    text: str,
    model: str,
    *,
    timeout_seconds: float | None = None,
) -> list[float]:
    """Embed 1 query duy nhất bằng Gemini (dùng task_type khác)."""
    from google import genai
    from google.genai import types

    result = call_with_key_rotation(
        _embedding_pool(tuple(settings.embedding_api_keys), settings.API_KEY_COOLDOWN_SECONDS),
        lambda key: _gemini_embed_query_once(
            genai, types, key, text, model, timeout_seconds=timeout_seconds,
        ),
        provider="embedding",
        max_attempts=1 if timeout_seconds is not None else None,
        slot_timeout_seconds=0 if timeout_seconds is not None else 10,
    )
    return result


def _gemini_embed_query_once(
    genai, types, api_key: str, text: str, model: str, *,
    timeout_seconds: float | None = None,
) -> list[float]:
    options = None
    if timeout_seconds is not None or current_budget():
        bounded_timeout = timeout_seconds or remaining_seconds(30.0)
        options = types.HttpOptions(
            timeout=max(1, int(bounded_timeout * 1000)),
            retry_options={"attempts": 1},
        )
    with physical_attempt("gemini", model):
        with genai.Client(api_key=api_key, http_options=options) as client:
            response = client.models.embed_content(
                model=model.removeprefix("models/"),
                contents=text,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=settings.EMBEDDING_DIMENSION,
                ),
            )
        _record_embedding_usage(response, "gemini", model)
    if not response.embeddings:
        raise ValueError("Gemini embedding provider returned no query vector.")
    return list(response.embeddings[0].values)


def _embed_with_local(
    texts: list[str],
    model: str,
    progress_callback: Callable[[float], None] | None = None,
) -> list[list[float]]:
    """Embed bằng mô hình Sentence-Transformers chạy local."""
    encoder = _get_local_encoder(model)
    vectors = encoder.encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    if progress_callback is not None:
        progress_callback(1.0)
    return vectors.tolist()


@lru_cache(maxsize=2)
def _get_local_encoder(model: str):
    """Load mỗi model local một lần trong suốt vòng đời process."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise ValueError(
            "EMBEDDING_PROVIDER=local cần package sentence-transformers. "
            "Hãy rebuild Docker hoặc chạy: pip install sentence-transformers."
        ) from error

    return SentenceTransformer(model)


def _embed_query_with_local(
    text: str,
    model: str,
) -> list[float]:
    """Embed một câu hỏi bằng cùng local encoder với tài liệu."""
    return _embed_with_local([text], model)[0]


def _embed_with_openai(
    texts: list[str],
    model: str,
    progress_callback: Callable[[float], None] | None = None,
) -> list[list[float]]:
    """Embed texts bằng OpenAI API."""
    from openai import OpenAI

    embeddings = []
    batch_size = 2048
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = call_with_key_rotation(
            _embedding_pool(tuple(settings.embedding_api_keys), settings.API_KEY_COOLDOWN_SECONDS),
            lambda key: _openai_embed_batch_once(OpenAI, key, batch, model),
            provider="embedding",
        )
        for item in response.data:
            embeddings.append(item.embedding)
        if progress_callback is not None:
            progress_callback(min(1.0, (i + len(batch)) / len(texts)))

    return embeddings


def _record_embedding_usage(response, provider: str, model: str) -> None:
    budget = current_budget()
    if budget is None:
        return
    usage = getattr(response, "usage_metadata" if provider == "gemini" else "usage", None)
    if usage is None:
        return
    if provider == "gemini":
        prompt = getattr(usage, "prompt_token_count", None)
        total = getattr(usage, "total_token_count", None)
    else:
        prompt = getattr(usage, "prompt_tokens", None)
        total = getattr(usage, "total_tokens", None)
    budget.record_usage(provider, model, {
        "prompt_tokens": prompt,
        "completion_tokens": 0,
        "total_tokens": total if total is not None else prompt,
    })


def _openai_embed_batch_once(OpenAI, api_key: str, batch: list[str], model: str):
    options = {}
    if current_budget():
        options.update(max_retries=0, timeout=remaining_seconds(30.0))
    with physical_attempt("openai", model):
        response = OpenAI(api_key=api_key, **options).embeddings.create(
            model=model,
            input=batch,
        )
        _record_embedding_usage(response, "openai", model)
        return response


def _openai_embed_query_once(OpenAI, api_key: str, text: str, model: str, timeout_seconds: float):
    options = {"timeout": timeout_seconds}
    if current_budget():
        options["max_retries"] = 0
        options["timeout"] = remaining_seconds(timeout_seconds)
    with physical_attempt("openai", model):
        response = OpenAI(api_key=api_key, **options).embeddings.create(
            model=model,
            input=[text],
        )
        _record_embedding_usage(response, "openai", model)
        return response


# =========================================================
# PUBLIC API
# =========================================================


def embed_texts(
    texts: list[str],
    progress_callback: Callable[[float], None] | None = None,
) -> list[list[float]]:
    """
    Embed danh sách texts thành vectors.
    Dùng cho document ingestion (batch).

    Returns:
        List of embedding vectors.
    """
    if not texts:
        return []

    provider = settings.EMBEDDING_PROVIDER
    model = settings.EMBEDDING_MODEL

    logger.info(
        "Embedding %d texts with %s/%s",
        len(texts),
        provider,
        model,
    )

    if provider == "local":
        vectors = _embed_with_local(texts, model, progress_callback=progress_callback)
    elif provider == "gemini":
        vectors = _embed_with_gemini(texts, model, progress_callback=progress_callback)
    elif provider == "openai":
        vectors = _embed_with_openai(texts, model, progress_callback=progress_callback)
    else:
        raise ValueError(
            f"Unknown embedding provider: {provider}. "
            f"Supported: local, gemini, openai"
        )

    return _validate_vectors(vectors, expected_count=len(texts))


def embed_query(text: str, *, timeout_seconds: float | None = None) -> list[float]:
    """
    Embed 1 câu query duy nhất.
    Dùng task_type khác (retrieval_query) cho Gemini
    để tối ưu kết quả search.

    Returns:
        Embedding vector.
    """
    # Cache successful vectors only, never answers or tenant document results.
    # The key includes the embedding space; callers get a fresh mutable list.
    return list(_cached_query_embedding(
        settings.EMBEDDING_PROVIDER, settings.EMBEDDING_MODEL,
        settings.EMBEDDING_DIMENSION, text.strip(),
        max(1, int(timeout_seconds * 1000)) if timeout_seconds is not None else None,
    ))


@lru_cache(maxsize=512)
def _cached_query_embedding(
    provider: str, model: str, dimension: int, text: str, timeout_ms: int | None = None,
) -> tuple[float, ...]:

    logger.info(
        "Embedding query with %s/%s",
        provider,
        model,
    )

    if provider == "local":
        vector = _embed_query_with_local(text, model)
    elif provider == "gemini":
        vector = _embed_query_with_gemini(
            text, model, timeout_seconds=timeout_ms / 1000 if timeout_ms is not None else None,
        )
    elif provider == "openai":
        if timeout_ms is None:
            vectors = _embed_with_openai([text], model)
        else:
            from openai import OpenAI

            response = call_with_key_rotation(
                _embedding_pool(tuple(settings.embedding_api_keys), settings.API_KEY_COOLDOWN_SECONDS),
                lambda key: _openai_embed_query_once(OpenAI, key, text, model, timeout_ms / 1000),
                provider="embedding",
                max_attempts=1,
                slot_timeout_seconds=0,
            )
            vectors = [item.embedding for item in response.data]
        vector = vectors[0]
    else:
        raise ValueError(
            f"Unknown embedding provider: {provider}. "
            f"Supported: local, gemini, openai"
        )

    return tuple(_validate_vectors([vector], expected_count=1)[0])


def embed_queries(texts: list[str]) -> list[list[float]]:
    """Embed evaluation/queued queries in batches using the same query task.

    Duplicate questions share one provider input. Failures abort the batch,
    so an evaluation cannot silently mix vector and lexical-only results.
    """
    if not texts:
        return []
    unique = list(dict.fromkeys(text.strip() for text in texts))
    provider, model = settings.EMBEDDING_PROVIDER, settings.EMBEDDING_MODEL
    if provider == "gemini":
        vectors = _embed_with_gemini(unique, model, task_type="RETRIEVAL_QUERY")
    elif provider == "local":
        vectors = _embed_with_local(unique, model)
    elif provider == "openai":
        vectors = _embed_with_openai(unique, model)
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")
    by_text = dict(zip(unique, _validate_vectors(vectors, expected_count=len(unique))))
    return [list(by_text[text.strip()]) for text in texts]
