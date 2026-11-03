"""Build source-grounded, provisional service/rental RAG retrieval cases.

The builder is read-only against application databases. It emits only positive
identity-retrieval cases when a service/rental catalog entry has a mapped,
ready document chunk that contains the exact catalog name. It does not create
answer text or infer an industry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping


_OBJECT_TYPES = {"service", "rental"}
_REGISTRY_STATES = {"active", "ready", "disabled"}
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def _tokens_with_spans(text: str) -> list[tuple[str, int, int]]:
    """Tokenize without accent folding: Vietnamese tone marks change meaning."""
    result = []
    for match in _TOKEN_RE.finditer(text):
        token = unicodedata.normalize("NFC", match.group(0).casefold())
        result.append((token, match.start(), match.end()))
    return result


def find_exact_identity_quote(identity: str, chunk_text: str) -> str | None:
    """Return the source substring when identity occurs as an exact token run."""
    identity_tokens = [token for token, _, _ in _tokens_with_spans(identity)]
    chunk_tokens = _tokens_with_spans(chunk_text)
    if not identity_tokens or len(identity_tokens) > len(chunk_tokens):
        return None
    for start in range(len(chunk_tokens) - len(identity_tokens) + 1):
        candidate = chunk_tokens[start : start + len(identity_tokens)]
        if [token for token, _, _ in candidate] == identity_tokens:
            return chunk_text[candidate[0][1] : candidate[-1][2]]
    return None


def _as_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _value(row: Mapping[str, object], key: str, default: object = None) -> object:
    return row.get(key, default)


def _identity_signature(name: str) -> tuple[str, ...]:
    return tuple(token for token, _, _ in _tokens_with_spans(name))


def _query_for(object_type: str, name: str) -> str:
    if object_type == "service":
        return f"Cho tôi thông tin về dịch vụ “{name}”."
    return f"Cho tôi thông tin về gói cho thuê “{name}”."


def build_cases(candidate_rows: Iterable[Mapping[str, object]], business_id: int) -> list[dict]:
    """Turn joined catalog/mapping/ready-chunk rows into pending positive cases.

    The input rows must contain the catalog, mapping, document and chunk fields
    selected by ``_candidate_rows`` below. The checks are repeated here so the
    pure builder remains safe when called from tests or another local tool.
    """
    business_id = _as_positive_int(business_id)
    if business_id is None:
        raise ValueError("business_id must be a positive integer")

    rows = list(candidate_rows)
    catalog_ids_by_identity: dict[tuple[str, tuple[str, ...]], set[int]] = defaultdict(set)
    for row in rows:
        if _as_positive_int(_value(row, "entry_business_id")) != business_id:
            continue
        object_type = str(_value(row, "object_type", "")).strip().casefold()
        entry_id = _as_positive_int(_value(row, "catalog_entry_id"))
        signature = _identity_signature(str(_value(row, "catalog_name", "")))
        if object_type in _OBJECT_TYPES and entry_id is not None and signature:
            catalog_ids_by_identity[(object_type, signature)].add(entry_id)
    ambiguous_identities = {
        identity for identity, entry_ids in catalog_ids_by_identity.items() if len(entry_ids) > 1
    }

    grouped: dict[tuple[str, int], dict] = {}
    for row in rows:
        entry_id = _as_positive_int(_value(row, "catalog_entry_id"))
        chunk_id = _as_positive_int(_value(row, "chunk_id"))
        document_id = _as_positive_int(_value(row, "document_id"))
        mapping_id = _as_positive_int(_value(row, "mapping_id"))
        if None in (entry_id, chunk_id, document_id, mapping_id):
            continue

        if _as_positive_int(_value(row, "entry_business_id")) != business_id:
            continue
        if _as_positive_int(_value(row, "document_business_id")) != business_id:
            continue
        if _as_positive_int(_value(row, "mapping_catalog_entry_id")) != entry_id:
            continue
        if _as_positive_int(_value(row, "mapping_chunk_id")) != chunk_id:
            continue

        object_type = str(_value(row, "object_type", "")).strip().casefold()
        if object_type not in _OBJECT_TYPES:
            continue
        if str(_value(row, "document_status", "")).strip().casefold() != "ready":
            continue

        name = " ".join(str(_value(row, "catalog_name", "")).split())
        chunk_text = str(_value(row, "chunk_content", "") or "")
        if (object_type, _identity_signature(name)) in ambiguous_identities:
            continue
        quote = find_exact_identity_quote(name, chunk_text)
        if not name or not chunk_text.strip() or quote is None:
            continue

        key = (object_type, entry_id)
        case = grouped.get(key)
        identity = {
            "business_id": business_id,
            "catalog_entry_id": entry_id,
            "object_type": object_type,
            "external_id": str(_value(row, "external_id", "")),
            "name": name,
            "revision": _as_positive_int(_value(row, "catalog_revision")),
            "status": str(_value(row, "catalog_status", "")),
            "availability": str(_value(row, "catalog_availability", "")),
        }
        if case is None:
            case = {
                "id": f"shop-{business_id}-{object_type}-{entry_id}-identity",
                "business_id": business_id,
                "case_type": f"{object_type}_identity_retrieval",
                "object_type": object_type,
                "query": _query_for(object_type, name),
                "expected_chunk_ids": set(),
                "catalog": identity,
                "source_refs": {},
                "expected_answer_scope": "Identify the named offer only; answer facts require human-defined scope.",
                "answer": None,
                "label_provenance": "agent_generated",
                "label_generator": "build_service_rental_rag_cases.py",
                "label_status": "pending_human_answer_scope",
                "retrieval_label_status": "agent_generated_source_supported",
                "answer_scope_status": "pending_human_answer_scope",
                "answer_quality_status": "pending_human_review",
                "human_review_status": "pending",
                "human_reviewed": False,
                "metric_eligible": True,
                "metric_eligibility_scope": "source_retrieval_only",
            }
            grouped[key] = case
        elif case["catalog"] != identity:
            # Conflicting catalog snapshots in one tenant read are unsafe to merge.
            raise ValueError(f"conflicting catalog identity for entry {entry_id}")

        source_key = (document_id, chunk_id, mapping_id)
        if source_key in case["source_refs"]:
            continue
        content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
        case["expected_chunk_ids"].add(chunk_id)
        case["source_refs"][source_key] = {
            "catalog_entry_id": entry_id,
            "mapping_id": mapping_id,
            "document_id": document_id,
            "document_filename": str(_value(row, "document_filename", "")),
            "document_content_hash": _value(row, "document_content_hash"),
            "document_status": "ready",
            "embedding_status": str(_value(row, "embedding_status", "")),
            "chunk_id": chunk_id,
            "chunk_index": _as_positive_int(_value(row, "chunk_index")) or 0,
            "chunk_sha256": content_hash,
            "identity_support_quote": quote,
        }

    result = []
    for case in grouped.values():
        case["expected_chunk_ids"] = sorted(case["expected_chunk_ids"])
        case["source_refs"] = sorted(
            case["source_refs"].values(),
            key=lambda ref: (ref["document_id"], ref["chunk_id"], ref["mapping_id"]),
        )
        result.append(case)
    return sorted(result, key=lambda case: (case["business_id"], case["object_type"], case["catalog"]["catalog_entry_id"]))


def _candidate_rows(db, business_id: int) -> list[Mapping[str, object]]:
    """Read only catalog entries with same-tenant mappings to ready documents."""
    from sqlalchemy import select

    from app.models.document import Document, DocumentChunk
    from app.models.recommendation_catalog import RecommendationCatalogChunkMapping, RecommendationCatalogEntry

    entry = RecommendationCatalogEntry
    mapping = RecommendationCatalogChunkMapping
    chunk = DocumentChunk
    document = Document
    statement = (
        select(
            entry.id.label("catalog_entry_id"),
            entry.business_id.label("entry_business_id"),
            entry.object_type.label("object_type"),
            entry.external_id.label("external_id"),
            entry.name.label("catalog_name"),
            entry.revision.label("catalog_revision"),
            entry.status.label("catalog_status"),
            entry.availability.label("catalog_availability"),
            mapping.id.label("mapping_id"),
            mapping.catalog_entry_id.label("mapping_catalog_entry_id"),
            mapping.document_chunk_id.label("mapping_chunk_id"),
            chunk.id.label("chunk_id"),
            chunk.chunk_index.label("chunk_index"),
            chunk.content.label("chunk_content"),
            document.id.label("document_id"),
            document.business_id.label("document_business_id"),
            document.filename.label("document_filename"),
            document.content_hash.label("document_content_hash"),
            document.status.label("document_status"),
            document.embedding_status.label("embedding_status"),
        )
        .outerjoin(mapping, mapping.catalog_entry_id == entry.id)
        .outerjoin(chunk, chunk.id == mapping.document_chunk_id)
        .outerjoin(
            document,
            (document.id == chunk.document_id)
            & (document.business_id == business_id)
            & (document.status == "ready"),
        )
        .where(
            entry.business_id == business_id,
            entry.object_type.in_(sorted(_OBJECT_TYPES)),
        )
        .order_by(entry.id, document.id, chunk.id, mapping.id)
    )
    return list(db.execute(statement).mappings().all())


def _registries(business_ids: set[int] | None = None) -> list[tuple[int, str]]:
    from sqlalchemy import select

    from app.database.platform_session import PlatformSessionLocal
    from app.models.platform_control import TenantRegistry
    from app.tenancy.schema import schema_name_for, validate_schema_name

    with PlatformSessionLocal() as db:
        rows = db.scalars(select(TenantRegistry).order_by(TenantRegistry.business_id)).all()
    result = []
    found: set[int] = set()
    for row in rows:
        business_id = int(row.business_id)
        schema = validate_schema_name(row.schema_name)
        if schema != schema_name_for(business_id):
            raise ValueError(f"tenant registry schema mismatch for business {business_id}")
        if str(row.state).casefold() not in _REGISTRY_STATES:
            continue
        if business_ids is None or business_id in business_ids:
            result.append((business_id, schema))
            found.add(business_id)
    if business_ids is not None and found != business_ids:
        missing = ", ".join(str(value) for value in sorted(business_ids - found))
        raise ValueError(f"business IDs are not in an eligible tenant registry: {missing}")
    return result


def build_from_databases(output: Path, business_ids: set[int] | None = None, *, overwrite: bool = False) -> dict:
    """Read eligible tenants and write JSONL without changing application data."""
    from app.database.tenant_session import tenant_session

    if output.exists() and not overwrite:
        raise FileExistsError(f"output already exists (pass --overwrite to replace): {output}")
    all_cases = []
    for business_id, schema in _registries(business_ids):
        with tenant_session(schema) as db:
            rows = _candidate_rows(db, business_id)
        all_cases.extend(build_cases(rows, business_id))

    output.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in all_cases)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=output.parent,
            prefix=f".{output.name}.", suffix=".tmp", delete=False,
        ) as temp_file:
            temp_name = temp_file.name
            temp_file.write(payload)
        Path(temp_name).replace(output)
    finally:
        if temp_name and Path(temp_name).exists():
            Path(temp_name).unlink()
    return {"output": str(output), "case_count": len(all_cases)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Destination JSONL path")
    parser.add_argument("--business-id", type=int, action="append", help="Limit to an eligible shop; repeatable")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output file")
    args = parser.parse_args(argv)
    if args.business_id and any(value <= 0 for value in args.business_id):
        parser.error("--business-id values must be positive integers")
    summary = build_from_databases(
        args.output,
        set(args.business_id) if args.business_id else None,
        overwrite=args.overwrite,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
