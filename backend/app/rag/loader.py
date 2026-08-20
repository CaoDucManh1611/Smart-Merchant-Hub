"""
Document loader – đọc nội dung từ nhiều định dạng file.

Hỗ trợ: PDF, DOCX, TXT, CSV, Markdown, HTML.
Output: raw text string.
"""

import csv
import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_pdf(file_bytes: bytes) -> str:
    """Đọc nội dung PDF."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"[Trang {i + 1}]\n{text}")
    return "\n\n".join(pages)


def load_docx(file_bytes: bytes) -> str:
    """Đọc nội dung DOCX."""
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def load_txt(file_bytes: bytes) -> str:
    """Đọc nội dung TXT."""
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    return file_bytes.decode("utf-8", errors="replace")


def load_csv(file_bytes: bytes) -> str:
    """Đọc nội dung CSV – chuyển mỗi row thành dòng text."""
    text = load_txt(file_bytes)
    reader = csv.reader(io.StringIO(text))
    rows = []
    for row in reader:
        rows.append(" | ".join(row))
    return "\n".join(rows)


def load_html(file_bytes: bytes) -> str:
    """Đọc nội dung HTML – strip tags, giữ text."""
    from bs4 import BeautifulSoup

    text = load_txt(file_bytes)
    soup = BeautifulSoup(text, "html.parser")

    # Xóa script, style tags
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    return soup.get_text(separator="\n", strip=True)


# =========================================================
# DISPATCHER
# =========================================================

LOADERS = {
    "pdf": load_pdf,
    "docx": load_docx,
    "txt": load_txt,
    "csv": load_csv,
    "md": load_txt,
    "html": load_html,
    "htm": load_html,
}


def detect_file_type(filename: str) -> str:
    """Trả về extension (lowercase, không có dấu chấm)."""
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext


def load_document(file_bytes: bytes, filename: str) -> str:
    """
    Load document từ bytes + filename.

    Raises ValueError nếu file type không được hỗ trợ.
    """
    file_type = detect_file_type(filename)

    loader = LOADERS.get(file_type)
    if loader is None:
        supported = ", ".join(sorted(LOADERS.keys()))
        raise ValueError(
            f"Không hỗ trợ file type '.{file_type}'. "
            f"Các loại được hỗ trợ: {supported}"
        )

    logger.info("Loading document: %s (type=%s)", filename, file_type)
    text = loader(file_bytes)

    if not text or not text.strip():
        raise ValueError(
            f"File '{filename}' không có nội dung text."
        )

    logger.info(
        "Loaded %d characters from %s",
        len(text),
        filename,
    )
    return text
