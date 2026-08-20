import logging
import re
import time

import google.generativeai as genai

from app.core.config import settings

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


def _embedding_api_key() -> str:
    """Use a dedicated embedding key, with legacy LLM_API_KEY fallback."""
    api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
    if not api_key:
        raise ValueError(
            "EMBEDDING_API_KEY chưa được cấu hình trong backend/.env."
        )
    return api_key


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
    return vectors


def _embed_with_gemini(
    texts: list[str],
    model: str,
) -> list[list[float]]:
    """Embed texts bằng Google Gemini API."""
    genai.configure(api_key=_embedding_api_key())

    embeddings = []
    # Gemini hỗ trợ batch nhưng giới hạn ~100 texts/request
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        for attempt in range(5):
            try:
                result = genai.embed_content(
                    model=f"models/{model}",
                    content=batch,
                    task_type="retrieval_document",
                )
                break
            except Exception as error:
                if "429" not in str(error) or attempt == 4:
                    raise
                delay = _gemini_retry_delay(error)
                logger.warning(
                    "Gemini embedding quota reached; retrying batch %d/%d in %ds (attempt %d/5)",
                    i // batch_size + 1,
                    (len(texts) + batch_size - 1) // batch_size,
                    delay,
                    attempt + 1,
                )
                time.sleep(delay)
        # result["embedding"] là list[list[float]] khi input là list
        if isinstance(result["embedding"][0], list):
            embeddings.extend(result["embedding"])
        else:
            embeddings.append(result["embedding"])

    return embeddings


def _embed_query_with_gemini(
    text: str,
    model: str,
) -> list[float]:
    """Embed 1 query duy nhất bằng Gemini (dùng task_type khác)."""
    genai.configure(api_key=_embedding_api_key())

    result = genai.embed_content(
        model=f"models/{model}",
        content=text,
        task_type="retrieval_query",
    )
    return result["embedding"]


def _embed_with_openai(
    texts: list[str],
    model: str,
) -> list[list[float]]:
    """Embed texts bằng OpenAI API."""
    from openai import OpenAI

    client = OpenAI(api_key=_embedding_api_key())

    embeddings = []
    batch_size = 2048
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(
            model=model,
            input=batch,
        )
        for item in response.data:
            embeddings.append(item.embedding)

    return embeddings


# =========================================================
# PUBLIC API
# =========================================================


def embed_texts(texts: list[str]) -> list[list[float]]:
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

    if provider == "gemini":
        vectors = _embed_with_gemini(texts, model)
    elif provider == "openai":
        vectors = _embed_with_openai(texts, model)
    else:
        raise ValueError(
            f"Unknown embedding provider: {provider}. "
            f"Supported: gemini, openai"
        )

    return _validate_vectors(vectors, expected_count=len(texts))


def embed_query(text: str) -> list[float]:
    """
    Embed 1 câu query duy nhất.
    Dùng task_type khác (retrieval_query) cho Gemini
    để tối ưu kết quả search.

    Returns:
        Embedding vector.
    """
    provider = settings.EMBEDDING_PROVIDER
    model = settings.EMBEDDING_MODEL

    logger.info(
        "Embedding query with %s/%s",
        provider,
        model,
    )

    if provider == "gemini":
        vector = _embed_query_with_gemini(text, model)
    elif provider == "openai":
        vectors = _embed_with_openai([text], model)
        vector = vectors[0]
    else:
        raise ValueError(
            f"Unknown embedding provider: {provider}. "
            f"Supported: gemini, openai"
        )

    return _validate_vectors([vector], expected_count=1)[0]
