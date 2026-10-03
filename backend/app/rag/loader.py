"""
Document loader – đọc nội dung từ nhiều định dạng file.

Hỗ trợ: PDF, DOCX, TXT, CSV, Markdown, HTML.
Output: raw text string.
"""

import csv
import io
import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


class DocumentValidationError(ValueError):
    """A stable, user-safe validation failure for an uploaded document."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
    parts = []
    for block in doc.iter_inner_content():
        if hasattr(block, "rows"):
            table_lines = []
            for row in block.rows:
                line = " | ".join(" ".join(cell.text.split()) for cell in row.cells)
                if line.strip(" |"):
                    table_lines.append("| " + line + " |")
            if table_lines:
                table_lines.insert(1, "| " + " | ".join("---" for _ in block.rows[0].cells) + " |")
                parts.append("\n".join(table_lines))
        elif block.text.strip():
            style = block.style.name if block.style is not None else ""
            level = style.removeprefix("Heading ")
            prefix = "#" * int(level) + " " if style.startswith("Heading ") and level.isdigit() and 1 <= int(level) <= 6 else ""
            parts.append(prefix + block.text)
    return "\n\n".join(parts)


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
        rows.append(" | ".join(cell.replace("\r", " ").replace("\n", " ") for cell in row))
    return "\n".join(rows)


def load_html(file_bytes: bytes) -> str:
    """Đọc nội dung HTML – strip tags, giữ text."""
    from bs4 import BeautifulSoup

    text = load_txt(file_bytes)
    soup = BeautifulSoup(text, "html.parser")

    # Xóa script, style tags
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        heading.replace_with("\n" + "#" * int(heading.name[1]) + " " + heading.get_text(" ", strip=True) + "\n")

    for table in soup.find_all("table"):
        rows = [row.find_all(["th", "td"]) for row in table.find_all("tr")]
        rows = [row for row in rows if row]
        if rows:
            lines = ["| " + " | ".join(cell.get_text(" ", strip=True) for cell in row) + " |" for row in rows]
            lines.insert(1, "| " + " | ".join("---" for _ in rows[0]) + " |")
            table.replace_with("\n" + "\n".join(lines) + "\n")

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


def validate_document_bytes(file_bytes: bytes, filename: str) -> None:
    """Validate format signatures and bound archive/text payloads before parsing."""
    file_type = detect_file_type(filename)
    if file_type not in LOADERS:
        supported = ", ".join(sorted(LOADERS.keys()))
        raise DocumentValidationError(
            "unsupported_file_type",
            f"Không hỗ trợ file type '.{file_type}'. Các loại được hỗ trợ: {supported}",
        )
    if not file_bytes:
        raise DocumentValidationError("empty_file", "File rỗng.")

    if file_type == "pdf":
        if b"%PDF-" not in file_bytes[:1024]:
            raise DocumentValidationError(
                "invalid_file_content",
                "Nội dung tệp không đúng định dạng PDF.",
            )
        return

    if file_type == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
                entries = archive.infolist()
                uncompressed_size = sum(entry.file_size for entry in entries)
                if (
                    len(entries) > 4096
                    or uncompressed_size > 100 * 1024 * 1024
                    or "word/document.xml" not in archive.namelist()
                ):
                    raise DocumentValidationError(
                        "invalid_file_content",
                        "Tệp DOCX không hợp lệ hoặc vượt giới hạn giải nén.",
                    )
        except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise DocumentValidationError(
                "invalid_file_content",
                "Nội dung tệp không đúng định dạng DOCX.",
            ) from exc
        return

    text = load_txt(file_bytes)
    if not text.strip():
        raise DocumentValidationError(
            "empty_extracted_text",
            "Tệp không có nội dung văn bản để lập chỉ mục.",
        )
    if "\x00" in text:
        raise DocumentValidationError(
            "invalid_file_content",
            "Tệp văn bản chứa dữ liệu không hợp lệ.",
        )
    control_count = sum(
        ord(character) < 32 and character not in "\t\n\r\f"
        or ord(character) == 127
        for character in text
    )
    if text and control_count / len(text) > 0.01:
        raise DocumentValidationError(
            "invalid_file_content",
            "Tệp văn bản chứa dữ liệu không hợp lệ.",
        )


def load_document(file_bytes: bytes, filename: str) -> str:
    """
    Load document từ bytes + filename.

    Raises ValueError nếu file type không được hỗ trợ.
    """
    validate_document_bytes(file_bytes, filename)
    file_type = detect_file_type(filename)

    loader = LOADERS.get(file_type)
    if loader is None:
        supported = ", ".join(sorted(LOADERS.keys()))
        raise DocumentValidationError(
            "unsupported_file_type",
            f"Không hỗ trợ file type '.{file_type}'. "
            f"Các loại được hỗ trợ: {supported}"
        )

    logger.info("Loading document type=%s bytes=%d", file_type, len(file_bytes))
    text = loader(file_bytes)

    if not text or not text.strip():
        raise DocumentValidationError(
            "empty_extracted_text",
            "Tài liệu không có nội dung văn bản để lập chỉ mục.",
        )

    logger.info(
        "Loaded %d characters from document type=%s",
        len(text),
        file_type,
    )
    return text
