"""Minimal source-citation gate for customer-facing RAG answers."""

import re
import unicodedata
from urllib.parse import urlsplit

from app.rag.lexical import CONCEPTS, contains, identifiers
from app.rag.topics import fold_topic_text


_CITATION = re.compile(r"\[(?:Nguồn|Source)\s+(\d+)\]", re.IGNORECASE)


def customer_facing_answer(answer: str) -> str:
    """Hide verified RAG source markers and Markdown from channel messages."""
    without_citations = re.sub(r"\[(?:Nguồn|Source)\s+\d+(?:\s*[,;]\s*\d+)*\]", "", answer or "", flags=re.IGNORECASE)
    without_markdown = without_citations.replace("***", "").replace("**", "")
    return "\n".join(re.sub(r"[ \t]+([.,;:!?])", r"\1", line.strip()) for line in without_markdown.splitlines()).strip()
_MONEY = re.compile(
    r"(?<!\w)(?:(?P<prefix>USD|VND|\$|₫)\s*(?P<prefix_amount>\d+(?:[., ]\d+)*)|"
    r"(?P<suffix_amount>\d+(?:[., ]\d+)*)\s*(?P<suffix>đồng|dong|VND|USD|đ|₫))(?!\w)",
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
_COMPATIBILITY_CUES = (
    "compatible", "compatibility", "fit", "fits", "work with", "works with",
    "tuong thich", "phu hop", "dung duoc", "lap duoc", "danh cho",
)
_COMPATIBILITY_UNCERTAINTY = (
    "chua xac nhan", "chua the xac nhan", "khong the xac nhan",
    "chua du can cu", "chua co du lieu", "khong co du lieu",
    "can kiem tra", "can nhan vien", "khong cam ket",
    "cannot confirm", "not confirmed", "not verified", "no evidence",
)
_VEHICLE_START = re.compile(r"\b(?:xe|dong xe|mau xe|vehicle|motorcycle)\s+([a-z0-9]+(?:\s+[a-z0-9]+){0,4})")
_VEHICLE_STOP_WORDS = {"doi", "nam", "phien", "ban", "the", "he", "mau", "loai", "cua", "toi", "minh", "khong", "co", "nha"}


def _vehicle_reference(value: str) -> str | None:
    folded = fold_topic_text(value)
    match = _VEHICLE_START.search(folded)
    if not match:
        return None
    tokens = []
    for token in match.group(1).split():
        if token in _VEHICLE_STOP_WORDS:
            break
        tokens.append(token)
        if len(tokens) == 4:
            break
    return " ".join(tokens) if tokens else None


def _compatibility_claim_is_supported(
    answer: str,
    cited_sources: list[str],
    query: str | None,
) -> bool:
    """Require an explicit model-to-product compatibility statement in one source row."""
    for line in (line.strip() for line in _CITATION.sub("", answer or "").splitlines()):
        folded_line = fold_topic_text(line)
        if not any(contains(folded_line, cue) for cue in _COMPATIBILITY_CUES):
            continue
        if any(contains(folded_line, phrase) for phrase in _COMPATIBILITY_UNCERTAINTY):
            continue

        vehicle = _vehicle_reference(query or "") or _vehicle_reference(line)
        if not vehicle:
            return False
        product_ids = set(identifiers(line)) or set(identifiers(query or ""))
        supported = False
        for source in cited_sources:
            source_lines = source.splitlines()
            for index, source_line in enumerate(source_lines):
                folded_source_line = fold_topic_text(source_line)
                if not contains(folded_source_line, vehicle):
                    continue
                has_compatibility_column = index > 0 and any(
                    contains(fold_topic_text(source_lines[index - 1]), cue) for cue in _COMPATIBILITY_CUES
                )
                if not (has_compatibility_column or any(contains(folded_source_line, cue) for cue in _COMPATIBILITY_CUES)):
                    continue
                if product_ids and not product_ids.issubset(set(identifiers(source_line))):
                    continue
                supported = True
                break
            if supported:
                break
        if not supported:
            return False
    return True


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
    return money_numbers | {str(int("".join(character for character in match if character.isdigit())))
                            for match in _NUMBER.findall(value)}


def verified_money_calculation(calculation: dict | list[dict], sources: list[str], query: str) -> str:
    """Recompute bounded arithmetic steps using only sourced/input operands."""
    steps = calculation if isinstance(calculation, list) else [calculation]
    if not steps or len(steps) > 6:
        raise ValueError("invalid_calculation_steps")
    money = set().union(*(_money_values(source) for source in sources))
    numbers = _number_values(query) | set().union(*(_number_values(source) for source in sources))
    derived = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("invalid_calculation_step")
        left, right = step.get("left"), step.get("right")
        if any(type(value) is not int or not 0 <= value <= 10**12 for value in (left, right)):
            raise ValueError("invalid_calculation_operands")
        if not {str(left), str(right)}.issubset(numbers):
            missing=sorted({str(left),str(right)}-numbers)
            raise ValueError("unsupported_calculation_operands: " + ", ".join(missing))
        operation = step.get("operation")
        monetary = any((str(v), "VND") in money for v in (left, right))
        if not monetary and not (operation == "subtract" and {str(left), str(right)}.issubset(_number_values(query))):
            raise ValueError("unsupported_calculation_operands")
        if operation == "multiply":
            result = left * right
        elif operation == "add":
            result = left + right
        elif operation == "subtract":
            result = left - right
        elif operation == "divide" and right and left % right == 0:
            result = left // right
        else:
            raise ValueError("unsupported_calculation")
        if not 0 <= result <= 10**12:
            raise ValueError("invalid_calculation_result")
        numbers.add(str(result))
        if monetary:
            money.add((str(result), "VND"))
        unit = "đồng" if monetary else "đơn vị"
        derived.append(f"Verified arithmetic ({operation}): {left}, {right}; result {result:,} {unit}.".replace(",", "."))
    if not monetary:
        raise ValueError("missing_monetary_result")
    return "\n".join(derived)


def _answer_concepts(value: str) -> set[str]:
    folded = fold_topic_text(value)
    folded = re.sub(r"\bcung cap\b", "", folded)
    folded = re.sub(r"\bavailable (?:data|information|details|evidence)\b", "", folded)
    # Order value is not a product-price claim (e.g. a shipping threshold).
    folded = re.sub(r"\b(?:tong )?gia tri(?: don hang| don)?\b", "", folded)
    concepts = set()
    for aliases in _ANSWER_CONCEPTS:
        concept_text = re.sub(r"\btuong thich\b", "", folded) if aliases[0] == "preference" else folded
        if any(contains(concept_text, alias) for alias in aliases):
            concepts.add(aliases[0])
    compatibility_lines = [
        fold_topic_text(line) for line in _CITATION.sub("", value or "").splitlines()
        if any(contains(fold_topic_text(line), cue) for cue in _COMPATIBILITY_CUES)
    ]
    if compatibility_lines and all(
        any(contains(line, phrase) for phrase in _COMPATIBILITY_UNCERTAINTY)
        for line in compatibility_lines
    ):
        concepts.discard("compatibility")
    return concepts


def _product_line_is_supported(
    answer: str,
    identifiers_in_answer: list[str],
    cited_sources: list[str],
    authoritative_sources: list[str] | None,
    query_numbers: set[str] | None = None,
) -> bool:
    """Keep a product's cited code and numeric facts together in its source row."""
    numeric_facts = _number_values(_CITATION.sub("", answer)) - (query_numbers or set())
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
    if not _compatibility_claim_is_supported(answer, cited_sources, query):
        return False
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
        requested_ids = set(identifiers(query or ""))
        if requested_ids:
            # Catalog evidence may contain many product rows in one source,
            # while a live product lookup is a multi-line block for one SKU.
            # Narrow multi-product sources to matching rows; retain the full
            # block only when it identifies a single product.
            matching_sources = []
            for source in authoritative_sources:
                source_ids = set(identifiers(source))
                if not requested_ids.intersection(source_ids):
                    continue
                if len(source_ids) > 1:
                    matching_sources.extend(
                        line for line in source.splitlines()
                        if requested_ids.intersection(identifiers(line))
                    )
                else:
                    matching_sources.append(source)
            answer_money = _money_values(answer)
            answer_numbers = _number_values(_CITATION.sub("", answer)) - _number_values(query or "")
            if not matching_sources and (answer_money or answer_numbers):
                return False
            if matching_sources:
                product_money = set().union(*(_money_values(source) for source in matching_sources))
                product_numbers = set().union(*(_number_values(source) for source in matching_sources))
                if not answer_money.issubset(product_money) or not answer_numbers.issubset(product_numbers):
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
        if not _product_line_is_supported(line, line_identifiers, line_sources, authoritative_sources, query_numbers):
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
