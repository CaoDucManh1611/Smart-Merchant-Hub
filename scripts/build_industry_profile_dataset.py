"""Build a structured dataset from the 15 DaNganh DOCX industry profiles.

The generated bundle intentionally separates knowledge candidates from evaluation
cases and dynamic catalog templates. It is safe to regenerate when the source
DOCX files change.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from docx import Document


DEFAULT_INPUT_DIR = Path(r"C:\Users\Administrator\Downloads\DaNganh")
DEFAULT_OUTPUT_DIR = Path("backend/artifacts/industry-profile-dataset")


def clean_text(value: str) -> str:
    text = (value or "").replace("\u00a0", " ").replace("\r", " ").replace("\n", " | ")
    text = re.sub(r"[ \t]+", " ", text).strip()
    # A subset of source paragraphs contains every character separated by one
    # space and each original word separated by three spaces. Repair only those
    # paragraphs so ordinary Vietnamese text remains untouched.
    tokens = text.split()
    single_ratio = (
        sum(1 for token in tokens if len(token) == 1) / len(tokens)
        if tokens
        else 0
    )
    if len(tokens) >= 20 and single_ratio >= 0.60 and "  " in value:
        text = re.sub(r"(?<=\S) (?=\S)", "", value)
        text = re.sub(r"\s{2,}", " ", text)
        text = text.replace("\u00a0", " ").strip()
    return text


def split_pipe(value: str) -> list[str]:
    return [item.strip() for item in clean_text(value).split("|") if item.strip()]


def split_csvish(value: str) -> list[str]:
    value = clean_text(value)
    return [item.strip() for item in value.split(",") if item.strip()]


def table_rows(table: Any) -> list[list[str]]:
    return [[clean_text(cell.text) for cell in row.cells] for row in table.rows]


def parse_title(doc: Document, source_path: Path) -> str:
    for paragraph in doc.paragraphs:
        if paragraph.style.name == "Title" and paragraph.text.strip():
            return clean_text(paragraph.text)
    stem = re.sub(r"^\d+-", "", source_path.stem)
    return stem.replace("-", " ").strip()


def parse_heading_key(text: str) -> str:
    return clean_text(text).lower()


def paragraph_records(doc: Document) -> list[dict[str, str]]:
    records = []
    for index, paragraph in enumerate(doc.paragraphs):
        text = clean_text(paragraph.text)
        if text:
            records.append(
                {
                    "paragraph_index": str(index),
                    "style": paragraph.style.name,
                    "text": text,
                }
            )
    return records


def extract_section_paragraphs(paragraphs: list[dict[str, str]]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "preamble"
    sections[current] = []
    for record in paragraphs:
        style = record["style"]
        text = record["text"]
        if style in {"Heading 1", "Heading 2"}:
            current = text
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(text)
    return {key: values for key, values in sections.items() if values}


def extract_qas(paragraphs: list[dict[str, str]], industry_id: str) -> list[dict[str, Any]]:
    qas: list[dict[str, Any]] = []
    start_indices = [
        index
        for index, record in enumerate(paragraphs)
        if record["style"] == "Heading 2" and re.match(r"^Q&A \d+ —", record["text"])
    ]
    for position, start in enumerate(start_indices):
        end = start_indices[position + 1] if position + 1 < len(start_indices) else len(paragraphs)
        block = [record["text"] for record in paragraphs[start:end]]
        heading = block[0]
        match = re.match(r"^Q&A\s+(\d+)\s+—\s+(.+)$", heading)
        if not match:
            continue
        fields: dict[str, str] = {}
        for line in block[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
        sources = split_csvish(fields.get("Nguồn cần truy xuất", ""))
        qas.append(
            {
                "case_id": match.group(2),
                "industry_id": industry_id,
                "case_number": int(match.group(1)),
                "question": fields.get("Câu hỏi", ""),
                "alternative_questions": split_pipe(fields.get("Cách hỏi khác", "")),
                "intent_id": fields.get("Intent", ""),
                "entities": split_csvish(fields.get("Thực thể", "")),
                "expected_answer": fields.get("Câu trả lời gợi ý", ""),
                "required_sources": sources,
                "retrieval_requirement": fields.get("Yêu cầu truy xuất", ""),
                "handoff_condition": fields.get("Điều kiện chuyển người", ""),
                "evaluation_only": True,
                "knowledge_ingest_candidate": True,
                "source_type": "synthetic_industry_qa",
            }
        )
    return qas


def extract_policy_blocks(paragraphs: list[dict[str, str]]) -> list[dict[str, Any]]:
    heading_indices = [
        index
        for index, record in enumerate(paragraphs)
        if record["style"] == "Heading 2"
        and any(
            marker in record["text"]
            for marker in [
                "sample_return",
                "sample_refund",
                "sample_shipping",
                "sample_inspection",
                "sample_damage",
                "sample_warranty",
            ]
        )
    ]
    policies = []
    for position, start in enumerate(heading_indices):
        end = heading_indices[position + 1] if position + 1 < len(heading_indices) else len(paragraphs)
        heading = paragraphs[start]["text"]
        policy_id = heading.split("—", 1)[-1].strip() if "—" in heading else heading
        policies.append(
            {
                "policy_id": policy_id,
                "title": heading,
                "content": [record["text"] for record in paragraphs[start + 1 : end]],
                "is_template_only": True,
            }
        )
    return policies


def extract_doc(source_path: Path) -> dict[str, Any]:
    doc = Document(str(source_path))
    source_match = re.match(r"^(\d+)-", source_path.name)
    industry_id = f"industry_{int(source_match.group(1)):02d}" if source_match else source_path.stem
    paragraphs = paragraph_records(doc)
    tables = [table_rows(table) for table in doc.tables]

    attributes = []
    for row in tables[0][1:]:
        if len(row) >= 6:
            attributes.append(
                {
                    "industry_id": industry_id,
                    "group": row[0],
                    "field_name": row[1],
                    "data_type": row[2],
                    "required": row[3],
                    "meaning": row[4],
                    "example_or_note": row[5],
                }
            )

    intents = []
    for row in tables[1][1:]:
        if len(row) >= 5:
            intent_parts = split_pipe(row[0])
            intents.append(
                {
                    "industry_id": industry_id,
                    "intent_id": intent_parts[0] if intent_parts else row[0],
                    "intent_group": intent_parts[1] if len(intent_parts) > 1 else "",
                    "description": row[1],
                    "entities": row[2],
                    "training_utterances": split_pipe(row[3]),
                    "source_handling_handoff": row[4],
                }
            )

    vocabulary = []
    for row in tables[2][1:]:
        if len(row) >= 5:
            vocabulary.append(
                {
                    "industry_id": industry_id,
                    "canonical_term": row[0],
                    "vietnamese_name": row[1],
                    "aliases": split_pipe(row[2]),
                    "abbreviation": row[3],
                    "scope": row[4],
                }
            )

    policy_fields = []
    for row in tables[3][1:]:
        if len(row) >= 5:
            policy_fields.append(
                {
                    "industry_id": industry_id,
                    "field_name": row[0],
                    "data_type": row[1],
                    "required": row[2],
                    "meaning": row[3],
                    "example_or_note": row[4],
                }
            )

    catalog_templates = []
    for row in tables[4][1:]:
        if len(row) >= 4:
            catalog_templates.append(
                {
                    "industry_id": industry_id,
                    "sample_sku": row[0],
                    "group": row[1],
                    "suggested_product_type": row[2],
                    "fields_to_complete": split_pipe(row[3]),
                    "synthetic": True,
                }
            )

    source_boundaries = []
    for table_index in (5, 6):
        for row in tables[table_index][1:]:
            if len(row) >= 3:
                source_boundaries.append(
                    {
                        "industry_id": industry_id,
                        "boundary_type": "source_precedence" if table_index == 5 else "missing_data_rule",
                        "question_or_data": row[0],
                        "primary_source": row[1],
                        "rule": row[2],
                    }
                )

    qas = extract_qas(paragraphs, industry_id)
    sections = extract_section_paragraphs(paragraphs)
    title = parse_title(doc, source_path)
    return {
        "industry_id": industry_id,
        "title": title,
        "source_file": str(source_path.resolve()),
        "source_filename": source_path.name,
        "attributes": attributes,
        "intents": intents,
        "vocabulary": vocabulary,
        "policy_fields": policy_fields,
        "catalog_templates": catalog_templates,
        "source_boundaries": source_boundaries,
        "sample_policies": extract_policy_blocks(paragraphs),
        "qas": qas,
        "sections": sections,
        "paragraphs": paragraphs,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flattened = dict(row)
            for key, value in flattened.items():
                if isinstance(value, (list, dict)):
                    flattened[key] = json.dumps(value, ensure_ascii=False)
            writer.writerow(flattened)


def build_markdown_bundle(profiles: list[dict[str, Any]]) -> str:
    lines = [
        "# Industry profile Q&A seed",
        "",
        "> Synthetic seed extracted from the 15 supplied DOCX files. Review and approve before using customer-facing. This document is suitable for a controlled RAG pilot; the JSONL case file remains the evaluation source of truth.",
        "",
    ]
    for profile in profiles:
        lines.extend([f"## {profile['industry_id']} {profile['title']}", ""])
        overview = profile["sections"].get("1. Tổng quan ngành", [])
        if overview:
            lines.extend(["### Phạm vi ngành", overview[0], ""])
        lines.append("### Thuật ngữ và FAQ")
        for term in profile["vocabulary"]:
            aliases = ", ".join(term["aliases"]) if term["aliases"] else ""
            lines.append(
                f"- **{term['canonical_term']}** ({term['vietnamese_name']}): {term['scope']} Aliases: {aliases}."
            )
        lines.append("")
        for case in profile["qas"]:
            lines.extend(
                [
                    f"#### {case['case_id']}",
                    f"**Câu hỏi:** {case['question']}",
                    f"**Cách hỏi khác:** {' | '.join(case['alternative_questions'])}",
                    f"**Intent:** {case['intent_id']}",
                    f"**Câu trả lời gợi ý:** {case['expected_answer']}",
                    f"**Nguồn cần truy xuất:** {', '.join(case['required_sources'])}",
                    f"**Điều kiện chuyển người:** {case['handoff_condition']}",
                    "",
                ]
            )
    return "\n".join(lines)


def build_readme(profiles: list[dict[str, Any]], counts: dict[str, int]) -> str:
    return f"""# Industry profile dataset

Dataset extracted from the 15 DOCX files under `C:\\Users\\Administrator\\Downloads\\DaNganh`.

## Contents

- `industry_profiles.json`: complete structured bundle, including source paragraphs.
- `rag_conversation_cases.jsonl`: {counts['qas']} synthetic Q&A cases for chatbot evaluation and review.
- `intent_examples.jsonl`: {counts['intents']} intent records with training utterances.
- `industry_vocabulary.jsonl`: {counts['vocabulary']} glossary records.
- `catalog_contract.jsonl`: {counts['catalog_templates']} synthetic `DEMO-*` catalog rows and fields to complete.
- `source_boundaries.jsonl`: source-precedence and missing-data rules.
- `industry_qa_seed.vi-en.md`: consolidated Markdown seed for a controlled RAG pilot.
- `rag_conversation_review_template.csv`: review sheet with blank bot-answer and correction columns.
- CSV companions for cases, intents, vocabulary and catalog templates.

## Recommended workflow

1. Use `industry_qa_seed.vi-en.md` as a reviewable seed document for a pilot RAG upload.
2. Use `rag_conversation_cases.jsonl` as the evaluation set. Do not upload this file as general knowledge.
3. For every run, append `bot_answer`, `review_status`, `corrected_answer` and `error_type` in a separate prediction/review file.
4. Keep prices, inventory, orders, appointments and tenant policy in structured Catalog/CRM/Policy sources; the `DEMO-*` rows are synthetic placeholders.
5. Do not treat sample policies as real policies until a shop approves them and adds scope and effective dates.

## Extraction notes

- Source Q&A and catalog examples are synthetic and may contain repeated or mechanically generated phrasing.
- The extractor repairs the character-spaced retrieval guidance found in some DOCX paragraphs.
- The source DOCX paragraphs are retained in `industry_profiles.json` so no content is silently discarded.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    source_files = sorted(args.input_dir.glob("*.docx"))
    if len(source_files) != 15:
        raise SystemExit(f"Expected 15 DOCX files in {args.input_dir}, found {len(source_files)}")

    profiles = [extract_doc(path) for path in source_files]
    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_qas = [case | {"source_filename": profile["source_filename"]} for profile in profiles for case in profile["qas"]]
    all_intents = [intent | {"source_filename": profile["source_filename"]} for profile in profiles for intent in profile["intents"]]
    all_vocabulary = [term | {"source_filename": profile["source_filename"]} for profile in profiles for term in profile["vocabulary"]]
    all_catalog = [row | {"source_filename": profile["source_filename"]} for profile in profiles for row in profile["catalog_templates"]]
    all_boundaries = [row | {"source_filename": profile["source_filename"]} for profile in profiles for row in profile["source_boundaries"]]

    counts = {
        "profiles": len(profiles),
        "qas": len(all_qas),
        "intents": len(all_intents),
        "vocabulary": len(all_vocabulary),
        "catalog_templates": len(all_catalog),
        "source_boundaries": len(all_boundaries),
    }
    write_json(args.output_dir / "industry_profiles.json", {"counts": counts, "profiles": profiles})
    write_jsonl(args.output_dir / "rag_conversation_cases.jsonl", all_qas)
    write_jsonl(args.output_dir / "intent_examples.jsonl", all_intents)
    write_jsonl(args.output_dir / "industry_vocabulary.jsonl", all_vocabulary)
    write_jsonl(args.output_dir / "catalog_contract.jsonl", all_catalog)
    write_jsonl(args.output_dir / "source_boundaries.jsonl", all_boundaries)
    write_csv(
        args.output_dir / "rag_conversation_cases.csv",
        all_qas,
        ["case_id", "industry_id", "case_number", "question", "alternative_questions", "intent_id", "entities", "expected_answer", "required_sources", "retrieval_requirement", "handoff_condition", "source_filename"],
    )
    review_rows = [
        case
        | {
            "bot_answer": "",
            "retrieved_sources": "",
            "citation_ok": "",
            "review_status": "",
            "error_type": "",
            "corrected_answer": "",
            "review_notes": "",
        }
        for case in all_qas
    ]
    write_csv(
        args.output_dir / "rag_conversation_review_template.csv",
        review_rows,
        [
            "case_id",
            "industry_id",
            "case_number",
            "question",
            "alternative_questions",
            "intent_id",
            "entities",
            "expected_answer",
            "required_sources",
            "retrieval_requirement",
            "handoff_condition",
            "source_filename",
            "bot_answer",
            "retrieved_sources",
            "citation_ok",
            "review_status",
            "error_type",
            "corrected_answer",
            "review_notes",
        ],
    )
    write_csv(
        args.output_dir / "intent_examples.csv",
        all_intents,
        ["industry_id", "intent_id", "intent_group", "description", "entities", "training_utterances", "source_handling_handoff", "source_filename"],
    )
    write_csv(
        args.output_dir / "industry_vocabulary.csv",
        all_vocabulary,
        ["industry_id", "canonical_term", "vietnamese_name", "aliases", "abbreviation", "scope", "source_filename"],
    )
    write_csv(
        args.output_dir / "catalog_contract.csv",
        all_catalog,
        ["industry_id", "sample_sku", "group", "suggested_product_type", "fields_to_complete", "synthetic", "source_filename"],
    )
    (args.output_dir / "industry_qa_seed.vi-en.md").write_text(
        build_markdown_bundle(profiles), encoding="utf-8"
    )
    (args.output_dir / "README.md").write_text(build_readme(profiles, counts), encoding="utf-8")

    duplicate_case_ids = [case_id for case_id, count in Counter(case["case_id"] for case in all_qas).items() if count > 1]
    print(json.dumps({"counts": counts, "duplicate_case_ids": duplicate_case_ids, "output_dir": str(args.output_dir.resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
