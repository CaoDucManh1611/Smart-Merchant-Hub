"""
Text chunker – chia text thành các đoạn nhỏ (chunks).

Sử dụng Recursive Character Text Splitter:
- Ưu tiên tách theo paragraph → sentence → word
- Có overlap giữa các chunks để giữ ngữ cảnh
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Thứ tự ưu tiên separators (tách paragraph trước, rồi sentence, rồi word)
DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]


@dataclass
class Chunk:
    """Một đoạn text đã được chunk."""

    content: str
    index: int
    metadata: dict


def _split_by_separator(text: str, separator: str) -> list[str]:
    """Tách text theo separator, giữ separator ở cuối mỗi phần."""
    if not separator:
        return list(text)
    parts = text.split(separator)
    result = []
    for i, part in enumerate(parts):
        if i < len(parts) - 1:
            result.append(part + separator)
        elif part:
            result.append(part)
    return result


def _recursive_split(
    text: str,
    chunk_size: int,
    separators: list[str],
) -> list[str]:
    """
    Chia text đệ quy: thử separator đầu tiên,
    nếu phần nào vẫn quá dài thì thử separator tiếp theo.
    """
    if len(text) <= chunk_size:
        return [text]

    # Tìm separator phù hợp
    current_sep = separators[0] if separators else ""
    remaining_seps = separators[1:] if len(separators) > 1 else []

    parts = _split_by_separator(text, current_sep)

    result = []
    for part in parts:
        if len(part) <= chunk_size:
            result.append(part)
        elif remaining_seps:
            # Phần quá dài → thử separator nhỏ hơn
            result.extend(
                _recursive_split(part, chunk_size, remaining_seps)
            )
        else:
            # Hết separator → cắt cứng theo chunk_size
            for i in range(0, len(part), chunk_size):
                result.append(part[i : i + chunk_size])

    return result


def _merge_with_overlap(
    parts: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """
    Gộp các phần nhỏ thành chunks có kích thước phù hợp,
    với overlap giữa các chunks liên tiếp.
    """
    chunks: list[str] = []
    current = ""

    for part in parts:
        # Nếu thêm part vào current mà quá chunk_size → lưu current
        if current and len(current) + len(part) > chunk_size:
            chunks.append(current.strip())

            # Tạo overlap nhưng không để overlap + part vượt chunk_size.
            overlap_size = min(
                chunk_overlap,
                len(current),
                max(0, chunk_size - len(part)),
            )
            current = current[-overlap_size:] + part if overlap_size else part
        else:
            current += part

    if current.strip():
        chunks.append(current.strip())

    return chunks


def chunk_text(
    text: str,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
    separators: list[str] | None = None,
    source_metadata: dict | None = None,
) -> list[Chunk]:
    """
    Chia text thành danh sách Chunk objects.

    Args:
        text: Nội dung text cần chunk
        chunk_size: Số ký tự tối đa mỗi chunk
        chunk_overlap: Số ký tự overlap giữa các chunks
        separators: Danh sách separators (ưu tiên từ trên xuống)
        source_metadata: Metadata bổ sung cho mỗi chunk

    Returns:
        Danh sách Chunk objects
    """
    if not text or not text.strip():
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size phải lớn hơn 0.")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap phải nằm trong khoảng [0, chunk_size).")

    if separators is None:
        separators = DEFAULT_SEPARATORS

    base_meta = source_metadata or {}

    # Bước 1: Tách đệ quy
    parts = _recursive_split(text, chunk_size, separators)

    # Bước 2: Gộp lại với overlap
    merged = _merge_with_overlap(parts, chunk_size, chunk_overlap)

    # Bước 3: Tạo Chunk objects
    chunks = []
    for i, content in enumerate(merged):
        if not content.strip():
            continue
        chunks.append(
            Chunk(
                content=content,
                index=i,
                metadata={
                    **base_meta,
                    "chunk_index": i,
                    "chunk_total": len(merged),
                    "char_count": len(content),
                },
            )
        )

    logger.info(
        "Chunked %d characters into %d chunks "
        "(size=%d, overlap=%d)",
        len(text),
        len(chunks),
        chunk_size,
        chunk_overlap,
    )

    return chunks
