"""Small, explainable topic router for the knowledge base."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path


TOPIC_TERMS: dict[str, tuple[str, ...]] = {
    "delivery": ("giao hang", "van chuyen", "phi ship", "cuoc ship", "nhan hang", "thoi gian giao"),
    "returns": ("doi tra", "doi hang", "tra hang", "hoan tien", "bao hanh"),
    "payments": ("thanh toan", "chuyen khoan", "tien mat", "cod", "hoa don", "vat"),
    "shop": ("thong tin shop", "gio ho tro", "kenh ho tro", "dia chi", "lien he"),
    "products": ("san pham", "sku", "ton kho", "gia niem yet", "danh muc", "mau sac", "kich thuoc"),
    "faq": ("cau hoi thuong gap", "huong dan", "tro ly", "ho tro khach hang"),
}


def fold_topic_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    normalized = normalized.replace("đ", "d")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())


def infer_document_topic(filename: str, text: str = "") -> str:
    """Infer a stable topic label from a filename and its headings/content."""
    filename_text = fold_topic_text(Path(filename or "").stem)
    folded = fold_topic_text(f"{filename_text} {text[:6000]}")
    scores = {
        topic: sum(2 if term in filename_text else 1 for term in terms if term in folded)
        for topic, terms in TOPIC_TERMS.items()
    }
    best_topic, best_score = max(scores.items(), key=lambda item: item[1])
    return best_topic if best_score else "faq"


def infer_query_topic(query: str) -> str | None:
    """Return a topic only when the query has a clear topic signal."""
    folded = fold_topic_text(query)
    scores = {
        topic: sum(1 for term in terms if term in folded)
        for topic, terms in TOPIC_TERMS.items()
    }
    best_topic, best_score = max(scores.items(), key=lambda item: item[1])
    return best_topic if best_score else None


def topic_matches(metadata: dict | None, topic: str | None) -> bool:
    return bool(topic and isinstance(metadata, dict) and metadata.get("topic") == topic)

