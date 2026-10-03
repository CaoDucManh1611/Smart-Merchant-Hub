"""Structure-aware, source-preserving RAG chunk boundaries."""

import json
import logging
import re
from collections.abc import Callable

from app.rag.chunker import Chunk

logger = logging.getLogger(__name__)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_SKU = re.compile(r"\bSKU\s+([A-Za-z0-9][A-Za-z0-9_.-]*)", re.IGNORECASE)
_DEPENDENT = re.compile(r"^(?:chỉ|không áp dụng|ngoại lệ|điều kiện|however|only if|except)\b", re.IGNORECASE)
_MAX_SEMANTIC_PARAGRAPHS = 16
_MAX_SEMANTIC_CHARS = 8000
_SENTENCE_END = re.compile(r'(?<=[.!?。！？])\s+(?=[A-ZÀ-Ỵ0-9“"\'])')
_ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "e.g.", "i.e.", "tp.", "ts.", "ths."}
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _parse_model_boundaries(raw: str, count: int) -> list[int] | None:
    """Only ordered, complete paragraph indexes can control source slicing."""
    try:
        ends = json.loads(raw.strip())
    except (TypeError, ValueError):
        return None
    if (not isinstance(ends, list) or not ends
            or not all(type(index) is int for index in ends)
            or ends != sorted(set(ends)) or ends[-1] != count
            or any(index < 1 or index > count for index in ends)):
        return None
    return ends


def _semantic_boundaries(parts: list[str]) -> list[int] | None:
    """Local conservative boundary hints; no source text leaves the machine."""
    if not parts:
        return None
    ends = []
    for index in range(1, len(parts) + 1):
        if index < len(parts) and _DEPENDENT.match(parts[index]):
            continue
        ends.append(index)
    return ends


def _paragraphs(text: str, chunk_size: int = 800) -> list[str]:
    """Long prose uses complete sentence boundaries, never a character cut."""
    result = []
    for part in re.split(r"\n\s*\n", text):
        part = part.strip()
        if not part:
            continue
        # ponytail: stdlib sentence hints; preserve unsplittable sentences rather than truncate them.
        if len(part) <= chunk_size or "```" in part or "~~~" in part:
            result.append(part)
            continue
        start = 0
        for match in _SENTENCE_END.finditer(part):
            token = part[:match.start()].rsplit(None, 1)[-1].casefold()
            if token in _ABBREVIATIONS or re.fullmatch(r"\d+\.", token):
                continue
            result.append(part[start:match.start()].strip())
            start = match.end()
        if part[start:].strip():
            result.append(part[start:].strip())
    return result


def contextual_embedding_text(chunk: Chunk) -> str:
    """Embed source-derived context; keep stored citation text unchanged."""
    context = chunk.metadata.get("context", "")
    return f"{context}\n\n{chunk.content}" if context else chunk.content


def _pack(parts: list[str], chunk_size: int) -> list[str]:
    """Soft size target; never split a source paragraph mid-statement."""
    result: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}\n\n{part}" if current else part
        if current and len(candidate) > chunk_size and not _DEPENDENT.match(part):
            result.append(current)
            current = part
        else:
            current = candidate
    if current:
        result.append(current)
    return result


def _semantic_segments(
    parts: list[str], chunk_size: int,
    detector: Callable[[list[str]], list[int] | None],
) -> list[str]:
    """Bound provider payloads and use only offsets into original paragraphs."""
    segments = []
    start = 0
    while start < len(parts):
        end = start
        size = 0
        while end < len(parts) and end - start < _MAX_SEMANTIC_PARAGRAPHS:
            next_size = size + len(parts[end]) + 2
            if end > start and next_size > _MAX_SEMANTIC_CHARS:
                break
            size = next_size
            end += 1
        batch = parts[start:end]
        boundaries = None
        if len(batch) > 1 and size <= _MAX_SEMANTIC_CHARS:
            try:
                boundaries = detector(batch)
            except Exception as error:
                logger.warning("Semantic chunking unavailable: error_type=%s", type(error).__name__)
        if (not isinstance(boundaries, list) or not boundaries
                or not all(type(index) is int for index in boundaries)
                or boundaries != sorted(set(boundaries)) or boundaries[-1] != len(batch)
                or any(index < 1 or index > len(batch) for index in boundaries)):
            boundaries = _semantic_boundaries(batch)
        previous = 0
        for boundary in boundaries or []:
            segments.extend(_pack(batch[previous:boundary], chunk_size))
            previous = boundary
        start = end
    return segments


def chunk_document(text: str, filename: str, *, chunk_size: int = 800,
                   source_metadata: dict | None = None,
                   semantic_boundary_detector: Callable[[list[str]], list[int] | None] | None = None) -> list[Chunk]:
    """Keep business units intact and record a same-document parent for retrieval."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not text or not text.strip():
        return []
    groups: list[tuple[str, str, list[str]]] = []
    lines = text.splitlines()

    def add_prose(section_lines: list[str], title: str) -> None:
        section = "\n".join(section_lines).strip()
        if section:
            parts = _paragraphs(section, chunk_size)
            segments = (_semantic_segments(parts, chunk_size, semantic_boundary_detector)
                        if semantic_boundary_detector else _pack(parts, chunk_size))
            groups.append(("section", title, segments))

    def add_section(section_lines: list[str], title: str) -> None:
        buffer = []
        index = 0
        while index < len(section_lines):
            if (index + 1 < len(section_lines) and "|" in section_lines[index]
                    and _TABLE_SEPARATOR.match(section_lines[index + 1])):
                add_prose(buffer, title)
                buffer = []
                header = "\n".join(section_lines[index:index + 2])
                index += 2
                while index < len(section_lines) and section_lines[index].strip().startswith("|"):
                    groups.append(("table_row", title, [f"{header}\n{section_lines[index]}"]))
                    index += 1
                continue
            buffer.append(section_lines[index])
            index += 1
        product_starts = [i for i, line in enumerate(buffer) if _SKU.search(line)]
        if len(product_starts) >= 2:
            add_prose(buffer[:product_starts[0]], title)
            for position, start in enumerate(product_starts):
                end = product_starts[position + 1] if position + 1 < len(product_starts) else len(buffer)
                groups.append(("product", title, ["\n".join(buffer[start:end]).strip()]))
        else:
            add_prose(buffer, title)
    if filename.lower().endswith(".csv") and len(lines) > 1:
        header = lines[0].strip()
        groups.extend(("product", line.strip(), [f"{header}\n{line.strip()}"])
                      for line in lines[1:] if line.strip())
    else:
        headings = []
        heading_path = []
        fenced = False
        for i, line in enumerate(lines):
            if line.strip().startswith(("```", "~~~")):
                fenced = not fenced
            match = _HEADING.match(line) if not fenced else None
            if match:
                level = len(line.lstrip().split()[0])
                while heading_path and heading_path[-1][0] >= level:
                    heading_path.pop()
                heading_path.append((level, match.group(1).strip()))
                headings.append((i, " > ".join(title for _, title in heading_path)))
        if headings:
            starts = ([(0, filename)] if headings[0][0] else []) + headings
            for position, (start, title) in enumerate(starts):
                end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
                section_lines = lines[start:end]
                add_section(section_lines, title)
        else:
            if any(_TABLE_SEPARATOR.match(line) for line in lines):
                add_section(lines, filename)
                parts = []
            else:
                parts = _paragraphs(text, chunk_size)
            if len(parts) == 1 and "\n- " in text and _SKU.search(text):
                parts = [line.strip() for line in lines if line.strip()]
            if parts and all(_SKU.search(part) for part in parts):
                groups.extend(("product", _SKU.search(part).group(1), [part]) for part in parts)
            elif parts:
                if semantic_boundary_detector:
                    segments = _semantic_segments(parts, chunk_size, semantic_boundary_detector)
                    groups.append(("freeform", filename, segments))
                else:
                    ends = _semantic_boundaries(parts)
                    if ends and ends == sorted(set(ends)) and ends[-1] == len(parts):
                        start = 0
                        segments = []
                        for end in ends:
                            segments.append("\n\n".join(parts[start:end]))
                            start = end
                        groups.append(("freeform", filename, segments))
                    else:
                        groups.append(("freeform", filename, _pack(parts, chunk_size)))

    chunks: list[Chunk] = []
    for parent_id, (kind, section, segments) in enumerate(groups):
        parent_start = len(chunks)
        for segment in segments:
            metadata = {**(source_metadata or {}), "source": filename,
                        "parent_id": parent_id, "section": section, "unit_type": kind,
                        "parent_start": parent_start, "parent_end": parent_start + len(segments) - 1,
                        "chunking_version": "structure-semantic-context-v2"}
            if kind == "product" and (sku := _SKU.search(segment)):
                metadata["sku"] = sku.group(1)
            context = f"Document: {filename[:200]}\nSection: {section[:300]}"
            if metadata.get("sku"):
                context += f"\nSKU: {metadata['sku']}"
            metadata["context"] = context
            chunks.append(Chunk(segment, len(chunks), metadata))
    for chunk in chunks:
        chunk.metadata.update(chunk_index=chunk.index, chunk_total=len(chunks), char_count=len(chunk.content))
    return chunks
