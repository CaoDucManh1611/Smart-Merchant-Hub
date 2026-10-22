"""Accent-insensitive bilingual lexical terms for Vietnamese commerce search."""
from __future__ import annotations

import re
import unicodedata

from app.rag.topics import fold_topic_text

STOP_WORDS = set("""
i a an the my your you we me am is are was do does did will would could can this that
these those it its of to for with and or as in on at by from have has be been run units unit applies
what which when where how someone please want need right now much many some any
toi minh ban shop khach hang co khong ko k thi la cua cho voi va hay hoac ve duoc
xin giup muon can nao gi bao nhieu nhu the vay day nay do roi luon mot nhung
con cong mau lam se lai de gui chiec phan loai nhe
san pham item items product products tell show know get
chinh sach policy policies customer customers
doc ky
""".split())

# Phrases express the same commerce concept; they do not add factual claims.
CONCEPTS = (
    ("pink", "hong"), ("gray", "grey", "xam"),
    ("shirt", "shirts", "ao thun"), ("bag", "bags", "tui"),
    ("jacket", "jackets", "ao khoac"), ("skirt", "chan vay"),
    ("charger", "chargers", "cu sac", "sac"),
    ("cable", "cables", "cap usb", "cap"),
    ("usb c", "type c", "usb type c"),
    ("cleanser", "cleansers", "sua rua mat"),
    ("cream", "moisturizer", "kem duong"),
    ("cookies", "cookie", "banh"), ("sesame", "sesame seeds", "hat me", "banh me"),
    ("collar", "vong co", "measurements", "measure", "fit"), ("pet", "dog", "thu cung"),
    ("stock", "available", "availability", "ton kho", "con hang", "het hang"),
    ("shipping", "delivery", "ship", "giao hang", "van chuyen", "phi ship"),
    ("return", "returns", "doi tra", "tra hang"),
    ("refund", "refunded", "hoan tien"),
    ("conditions", "condition", "eligible", "eligibility", "dieu kien"),
    ("days", "day", "ngay"), ("sku", "skus", "ma hang", "ma san pham"),
    ("wholesale", "bulk", "nhap si", "mua si", "ban si"),
    ("discount", "tier", "giam gia", "chiet khau"),
    ("allergy", "allergic", "allergen", "allergens", "di ung"),
    ("ingredients", "ingredient", "thanh phan"),
    ("safety", "safe", "an toan"), ("skin", "da nhay cam"),
    ("compatibility", "compatible", "work with", "tuong thich"),
    ("invoice", "tax invoice", "hoa don"),
    ("payment", "charged", "thanh toan", "doi soat"),
    ("preference", "prefer", "preferences", "remember", "store", "stored", "save", "saved", "so thich", "thich", "ghi nho", "luu"),
    ("occupation", "police", "officer", "job", "nghe nghiep", "nghe gi", "cong an"),
    ("advertising", "marketing", "targeting", "personalize offers", "target offers", "quang cao", "nham muc tieu"),
    ("segment", "segmentation", "classify", "categorize", "phan loai", "phan khuc"),
    ("purchase", "purchased", "bought", "single purchase", "mua mot mon"),
    ("treatment", "treat", "clinical outcome", "medical effect", "dieu tri"),
    ("another customer", "other customer", "different customer", "khach khac", "another customer s order"),
    ("gift", "qua tang"), ("appointment", "appointments", "booking", "book", "consultation", "slot", "dat lich", "lich hen", "tu van"),
    ("setup", "set up", "thiet lap"),
    ("privacy", "private", "quyen rieng tu", "bao mat"),
)

def contains(text: str, term: str) -> bool:
    return f" {term} " in f" {text} "

def identifiers(query: str) -> list[str]:
    query = unicodedata.normalize("NFKC", query).translate(str.maketrans({
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    }))
    return list(dict.fromkeys(
        match.casefold() for match in re.findall(r"\b[\w]+(?:[-_][\w]+)+\b", query)
        if any(c.isdigit() for c in match) and any(c.isalpha() for c in match)
        and not re.fullmatch(r"\d+(?:-\d+)?[-_](?:units?|packs?|pieces?|pcs|items?|ml|kg|days?|hours?|cai|chiec|ngay)", match, re.I)
    ))

def query_terms(query: str) -> list[tuple[str, ...]]:
    folded = re.sub(r"\bgiai thich\b", "", fold_topic_text(query))
    terms = []
    consumed = set()
    for aliases in CONCEPTS:
        # An occupation mentioned alongside a concrete product is incidental;
        # it must not dilute the product/color evidence used for retrieval.
        if aliases[0] == "occupation" and any(contains(folded, term) for term in (
            "shirt", "ao thun", "cable", "cap usb", "pink", "hong", "charger", "cu sac",
            "cleanser", "sua rua mat", "collar", "vong co", "product", "san pham",
        )):
            for alias in aliases:
                if contains(folded, alias):
                    consumed.update(alias.split())
            continue
        if any(contains(folded, alias) for alias in aliases):
            terms.append(aliases)
            for alias in aliases:
                if contains(folded, alias):
                    consumed.update(alias.split())
    for word in dict.fromkeys(folded.split()):
        if word not in STOP_WORDS and word not in consumed and len(word) > 1:
            terms.append((word,))
    return terms[:24]

