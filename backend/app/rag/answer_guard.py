"""Minimal source-citation gate for customer-facing RAG answers."""

import re


_CITATION = re.compile(r"\[(?:Nguồn|Source)\s+(\d+)\]", re.IGNORECASE)
_MONEY = re.compile(
    r"(?<!\w)(?:(?P<prefix>USD|VND|\$|₫)\s*(?P<prefix_amount>\d+(?:[.,]\d+)*)|"
    r"(?P<suffix_amount>\d+(?:[.,]\d+)*)\s*(?P<suffix>đồng|VND|USD|đ|₫))(?!\w)",
    re.IGNORECASE,
)


def _money_values(value: str) -> set[tuple[str, str]]:
    return {
        (
            "".join(char for char in (match.group("prefix_amount") or match.group("suffix_amount")) if char.isdigit()),
            "USD" if (match.group("prefix") or match.group("suffix")).lower() in {"usd", "$"} else "VND",
        )
        for match in _MONEY.finditer(value or "")
    }


def has_valid_citations(answer: str, source_texts: list[str]) -> bool:
    """Accept only answers citing at least one retrieved, in-range source.

    This verifies attribution, not whether the cited passage proves every
    claim. Staff should still review consequential price or policy answers.
    """
    ids = [int(value) for value in _CITATION.findall(answer or "")]
    if not ids or not all(1 <= value <= len(source_texts) for value in ids):
        return False
    # A citation marker alone does not justify an invented price. Refuse
    # monetary values absent from the passages actually cited by the answer.
    cited_money = set().union(*(_money_values(source_texts[index - 1]) for index in ids))
    return _money_values(answer).issubset(cited_money)
