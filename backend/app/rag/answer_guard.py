"""Minimal source-citation gate for customer-facing RAG answers."""

import re
import unicodedata
from urllib.parse import urlsplit

from app.rag.lexical import CONCEPTS, contains, identifiers
from app.rag.topics import fold_topic_text


_CITATION = re.compile(r"\[(?:Nguồn|Source)\s+(\d+)\]", re.IGNORECASE)


def customer_facing_answer(answer: str) -> str:
    """Hide verified RAG source markers and Markdown from channel messages."""
    without_citations = _CITATION.sub("", answer or "")
    without_markdown = without_citations.replace("***", "").replace("**", "")
    return "\n".join(line.strip() for line in without_markdown.splitlines()).strip()
_MONEY = re.compile(
    r"(?<!\w)(?:(?P<prefix>USD|VND|\$|₫)\s*(?P<prefix_amount>\d+(?:[., ]\d+)*)|"
    r"(?P<suffix_amount>\d+(?:[., ]\d+)*)\s*(?P<suffix>đồng|VND|USD|đ|₫))(?!\w)",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s<>\]\[(){}]+", re.IGNORECASE)
_PLACEHOLDER_URL_HINT = re.compile(r"\b(?:demo|test|example only|placeholder|sample link|ví dụ|minh họa|minh hoa|không dùng để đặt|not for real orders)\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?<!\w)\d+(?:[., ]\d+)*(?!\w)")
_IDENTIFIER_WITH_NUMBERS = re.compile(r"\b(?=[\w-]*[a-z])(?=[\w-]*\d)[\w]+(?:[-_][\w]+)+\b", re.IGNORECASE)
_ANSWER_CONCEPTS = (*CONCEPTS,
    ("price", "prices", "gia", "cost", "costs", "unit price"),
    ("size", "sizes", "kich thuoc", "size range"),
    ("color", "colour", "colors", "colours", "mau sac"),
)


def _money_values(value: str) -> set[tuple[str, str]]:
    value = unicodedata.normalize("NFKC", value or "")
    values = {
        (
            "".join(char for char in (match.group("prefix_amount") or match.group("suffix_amount")) if char.isdigit()),
            "USD" if (match.group("prefix") or match.group("suffix")).lower() in {"usd", "$"} else "VND",
        )
        for match in _MONEY.finditer(value or "")
    }
    folded_lines = [
        unicodedata.normalize("NFKD", line.casefold()).encode("ascii", "ignore").decode("ascii")
        for line in value.splitlines()
    ]
    price_headers = {"price", "price vnd", "price_vnd", "unit price", "gia", "gia ban", "don gia"}
    for index, line in enumerate(folded_lines[:-1]):
        cells = [cell.strip(" *`:") for cell in line.split("|")]
        header_index = next((i for i, cell in enumerate(cells) if cell in price_headers), None)
        if header_index is None:
            continue
        for row in folded_lines[index + 1:]:
            if "|" not in row:
                break
            row_cells = [cell.strip(" *`:") for cell in row.split("|")]
            if len(row_cells) <= header_index:
                break
            digits = "".join(char for char in row_cells[header_index] if char.isdigit())
            if digits:
                values.add((digits, "VND"))
    return values


def _number_values(value: str) -> set[str]:
    """Normalize numeric facts after removing SKU/model identifiers."""
    value = unicodedata.normalize("NFKC", value or "").translate(str.maketrans({
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    }))
    value = re.sub(r"^[ \t]*(?:[-*+][ \t]+|\d+[.)][ \t]+)", "", value, flags=re.MULTILINE)
    value = _IDENTIFIER_WITH_NUMBERS.sub(lambda match: " " if identifiers(match.group()) else match.group(), value)
    money_numbers = {amount for amount, _currency in _money_values(value)}
    value = _MONEY.sub(" ", value)
    return money_numbers | {"".join(character for character in match if character.isdigit())
                            for match in _NUMBER.findall(value)}


def _answer_concepts(value: str) -> set[str]:
    folded = fold_topic_text(value)
    folded = re.sub(r"\bavailable (?:data|information|details|evidence)\b", "", folded)
    # Order value is not a product-price claim (e.g. a shipping threshold).
    folded = re.sub(r"\b(?:tong )?gia tri(?: don hang| don)?\b", "", folded)
    return {
        aliases[0] for aliases in _ANSWER_CONCEPTS
        if any(contains(folded, alias) for alias in aliases)
    }


def _product_line_is_supported(
    answer: str,
    identifiers_in_answer: list[str],
    cited_sources: list[str],
    authoritative_sources: list[str] | None,
) -> bool:
    """Keep a product's cited code and numeric facts together in its source row."""
    numeric_facts = _number_values(_CITATION.sub("", answer))
    if len(identifiers_in_answer) != 1 or not numeric_facts:
        return True

    product_id = identifiers_in_answer[0]
    current_rows = [
        line for source in (authoritative_sources or []) for line in source.splitlines()
        if product_id in identifiers(line)
    ]
    sources = authoritative_sources if current_rows else cited_sources
    for source in sources or []:
        matching_rows = [line for line in source.splitlines() if product_id in identifiers(line)]
        if matching_rows and any(numeric_facts.issubset(_number_values(line)) for line in matching_rows):
            return True
        # Markdown knowledge often places one product's details on adjacent
        # lines. Allow the whole chunk only when it cannot mix multiple SKUs.
        source_ids = set(identifiers(source))
        if source_ids == {product_id} and numeric_facts.issubset(_number_values(source)):
            return True
    return False


def has_valid_citations(
    answer: str,
    source_texts: list[str],
    *,
    authoritative_sources: list[str] | None = None,
    query: str | None = None,
) -> bool:
    """Accept only answers citing at least one retrieved, in-range source.

    This verifies attribution, not whether the cited passage proves every
    claim. Staff should still review consequential price or policy answers.
    """
    ids = [int(value) for value in _CITATION.findall(answer or "")]
    if not ids or not all(1 <= value <= len(source_texts) for value in ids):
        return False
    cited_sources = [source_texts[index - 1] for index in ids]
    # A citation marker alone does not justify invented prices, product codes,
    # or links. Check each against the text explicitly cited by the answer.
    cited_money = set().union(*(_money_values(source) for source in cited_sources))
    if not _money_values(answer).issubset(cited_money):
        return False
    # Do not let a citation for a policy containing different numbers justify
    # an invented quantity, duration, percentage, or threshold. Echoed input
    # numbers are context, not newly asserted shop facts.
    answer_numbers = _number_values(_CITATION.sub("", answer))
    query_numbers = _number_values(query or "")
    cited_numbers = set().union(*(_number_values(source) for source in cited_sources))
    if not (answer_numbers - query_numbers).issubset(cited_numbers):
        return False
    # Only serving code supplies current CRM facts. Uploaded documents cannot
    # mark themselves authoritative, and a stale cited price cannot override CRM.
    if authoritative_sources:
        current_money = set().union(*(_money_values(source) for source in authoritative_sources))
        if not _money_values(answer).issubset(current_money):
            return False
    cited_identifiers = set().union(*(set(identifiers(source)) for source in cited_sources))
    if not set(identifiers(answer)).issubset(cited_identifiers):
        return False
    # A valid source number must also support the answer's actual topic; a
    # citation to an unrelated passage is not enough by itself.
    answer_concepts = _answer_concepts(answer)
    cited_concepts = set().union(*(_answer_concepts(source) for source in cited_sources))
    if not answer_concepts.issubset(cited_concepts):
        return False
    # A citation to the right document is not enough if the answer combines a
    # product code from one row with another row's stock, size, or price.
    for line in (line.strip(" |\t") for line in (answer or "").splitlines()):
        line_ids = [int(value) for value in _CITATION.findall(line)]
        line_sources = [source_texts[index - 1] for index in line_ids] if line_ids else cited_sources
        line = _CITATION.sub("", line).strip()
        if line_ids:
            if not _money_values(line).issubset(set().union(*(_money_values(source) for source in line_sources))):
                return False
            if not (_number_values(line) - query_numbers).issubset(set().union(*(_number_values(source) for source in line_sources))):
                return False
        line_identifiers = identifiers(line)
        if not _product_line_is_supported(line, line_identifiers, line_sources, authoritative_sources):
            return False
    cited_urls = {
        unicodedata.normalize("NFKC", url).rstrip(".,;:!? ").casefold()
        for source in cited_sources for url in _URL.findall(source)
    }
    answer_urls = {
        unicodedata.normalize("NFKC", url).rstrip(".,;:!? ").casefold()
        for url in _URL.findall(answer)
    }
    if not answer_urls.issubset(cited_urls):
        return False
    placeholder_domains = {"example.com", "example.org", "example.net", "localhost"}
    for url in answer_urls:
        try:
            host = (urlsplit(url).hostname or "").casefold()
        except ValueError:
            return False
        is_placeholder = host in placeholder_domains or host.endswith(".test")
        explanation = _URL.sub("", answer)
        if is_placeholder and not _PLACEHOLDER_URL_HINT.search(explanation):
            return False
    return True
