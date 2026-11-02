"""Prepare immutable shop catalog/knowledge snapshots and run offline answer arms."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys
import time

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.models.document import Document, DocumentChunk
from app.models.platform_control import TenantRegistry
from app.models.sales import Product
from app.rag.agentic_controller import corrective_query, evidence_quality, retrieval_is_weak
from app.rag.catalog_filters import extract_query_hard_filters
from app.rag.prompt_builder import build_prompt
from app.rag.retriever import RetrievedChunk, retrieve
from app.tenancy.schema import schema_name_for, validate_schema_name


SHOPS = (1, 4, 7)
TARGET_CASES = 40
ANSWER_MAX_COMPLETION_TOKENS = 1024


def _hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _schemas() -> dict[int, str]:
    with PlatformSessionLocal() as db:
        rows = db.scalars(select(TenantRegistry).where(TenantRegistry.business_id.in_(SHOPS))).all()
        result = {int(row.business_id): validate_schema_name(row.schema_name) for row in rows}
    for shop_id, schema in result.items():
        if schema != schema_name_for(shop_id):
            raise ValueError(f"Tenant schema registry mismatch for shop {shop_id}")
    missing = set(SHOPS) - result.keys()
    if missing:
        raise ValueError(f"Missing tenant schemas: {sorted(missing)}")
    return result


def _product_json(row: Product) -> dict:
    return {
        "product_id": row.id,
        "sku": row.sku,
        "name": row.name,
        "description": row.description,
        "price": str(row.price),
        "stock_quantity": int(row.stock_quantity),
        "reserved_quantity": int(row.reserved_quantity or 0),
        "available_quantity": max(0, int(row.stock_quantity) - int(row.reserved_quantity or 0)),
        "status": row.status,
        "metadata": row.metadata_ if isinstance(row.metadata_, dict) else {},
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _source_ref(filename: str, document_hash: str, content: str) -> str:
    return f"doc:{document_hash or 'nohash'}:chunk:{_hash(content)}"


def _snapshot() -> dict:
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    shops: dict[str, dict] = {}
    for shop_id, schema in _schemas().items():
        with tenant_session(schema) as db:
            products = [_product_json(row) for row in db.scalars(
                select(Product).where(Product.business_id == shop_id).order_by(Product.id)
            ).all()]
            documents = db.scalars(select(Document).where(
                Document.business_id == shop_id, Document.status == "ready"
            ).order_by(Document.id)).all()
            doc_ids = [row.id for row in documents]
            chunks = db.scalars(select(DocumentChunk).where(
                DocumentChunk.document_id.in_(doc_ids)
            ).order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)).all() if doc_ids else []
            by_id = {row.id: row for row in documents}
            sources = [{
                "document_id": row.id,
                "filename": row.filename,
                "file_type": row.file_type,
                "content_hash": row.content_hash,
                "processed_at": row.processed_at.isoformat() if row.processed_at else None,
                "chunks": [{
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "source_ref": _source_ref(row.filename, row.content_hash or "", chunk.content),
                } for chunk in chunks if chunk.document_id == row.id],
            } for row in documents]
        payload = {"business_id": shop_id, "fetched_at": fetched_at, "products": products, "documents": sources}
        payload["snapshot_id"] = _hash(payload)
        shops[str(shop_id)] = payload
    return {"schema_version": 1, "generated_at": fetched_at, "shops": shops}


def _product_sources(shop: dict, product: dict) -> list[str]:
    sku, name = str(product["sku"]).casefold(), str(product["name"]).casefold()
    return [chunk["source_ref"] for doc in shop["documents"] for chunk in doc["chunks"]
            if sku in chunk["content"].casefold() or name in chunk["content"].casefold()]


def _policy_source(shop: dict) -> dict | None:
    candidates = []
    for doc in shop["documents"]:
        for chunk in doc["chunks"]:
            text = chunk["content"].casefold()
            if any(term in text for term in ("đổi trả", "hoàn tiền", "bảo hành", "vận chuyển", "giao hàng")):
                candidates.append(chunk)
    return candidates[0] if candidates else None


def _make_cases(snapshot: dict) -> list[dict]:
    cases = []
    for shop_key, shop in snapshot["shops"].items():
        shop_id = int(shop_key)
        products = [p for p in shop["products"] if p["status"].casefold() in {"active", "available", "on_sale"}]
        products.sort(key=lambda p: (p["available_quantity"] > 0, p["product_id"]))
        selected = products[:3]
        for product in selected:
            base = {"business_id": shop_id, "catalog_snapshot_id": shop["snapshot_id"],
                    "catalog_product_id": product["product_id"], "sku": product["sku"],
                    "suggested_source_refs": _product_sources(shop, product),
                    "human_review": {"status": "pending", "reviewer": None, "reviewed_at": None}}
            for kind, query, facts in (
                ("price", f"{product['name']} giá hiện tại bao nhiêu?", {"price": product["price"]}),
                ("stock", f"{product['name']} còn bao nhiêu?", {"available_quantity": product["available_quantity"]}),
            ):
                cases.append({**base, "case_id": f"shop{shop_id}_{product['product_id']}_{kind}",
                              "case_type": kind, "query": query, "expected_facts": facts,
                              "expected_action": "lookup_product", "answer_contract": "Trả đúng theo snapshot shop; không tự đoán."})
        if selected:
            product = selected[0]
            cases.append({"case_id": f"shop{shop_id}_{product['product_id']}_sku_exact", "business_id": shop_id,
                          "catalog_snapshot_id": shop["snapshot_id"], "catalog_product_id": product["product_id"],
                          "case_type": "sku_exact", "query": f"Mã SKU {product['sku']} tên hàng gì và hiện còn bán không?",
                          "sku": product["sku"], "expected_facts": {"name": product["name"],
                          "status": product["status"], "available_quantity": product["available_quantity"]},
                          "expected_action": "lookup_product_by_sku", "suggested_source_refs": _product_sources(shop, product),
                          "human_review": {"status": "pending", "reviewer": None, "reviewed_at": None},
                          "answer_contract": "Khớp đúng SKU; tên và tình trạng bán lấy từ snapshot."})
        unknown = f"EVAL-NOT-FOUND-SHOP-{shop_id}-9XZ"
        cases.append({"case_id": f"shop{shop_id}_unknown_sku", "business_id": shop_id,
                      "catalog_snapshot_id": shop["snapshot_id"], "case_type": "unknown_sku",
                      "query": f"Mã {unknown} còn hàng và giá bao nhiêu?", "sku": unknown,
                      "expected_facts": {"sku_exists": False}, "expected_action": "clarify_or_handoff",
                      "suggested_source_refs": [], "human_review": {"status": "pending", "reviewer": None, "reviewed_at": None},
                      "answer_contract": "Báo không tìm thấy mã trong snapshot; không đoán giá/tồn."})
        if selected:
            product = min(selected, key=lambda p: p["available_quantity"])
            cases.append({"case_id": f"shop{shop_id}_{product['product_id']}_availability", "business_id": shop_id,
                          "catalog_snapshot_id": shop["snapshot_id"], "catalog_product_id": product["product_id"],
                          "case_type": "availability", "query": f"{product['name']} hiện còn hàng để đặt không?",
                          "sku": product["sku"], "expected_facts": {"available_quantity": product["available_quantity"]},
                          "expected_action": "lookup_product", "suggested_source_refs": _product_sources(shop, product),
                          "human_review": {"status": "pending", "reviewer": None, "reviewed_at": None},
                          "answer_contract": "Trả trạng thái và số lượng khả dụng theo snapshot; không dùng tồn kho thô nếu có hàng giữ."})
        policy = _policy_source(shop)
        if policy:
            cases.append({"case_id": f"shop{shop_id}_policy", "business_id": shop_id,
                          "catalog_snapshot_id": shop["snapshot_id"], "case_type": "policy",
                          "query": "Shop áp dụng chính sách đổi trả hoặc bảo hành như thế nào?",
                          "expected_facts": {}, "expected_action": "answer_from_source",
                          "suggested_source_refs": [policy["source_ref"]],
                          "human_review": {"status": "pending", "reviewer": None, "reviewed_at": None},
                          "answer_contract": "Chỉ nêu điều khoản được nguồn shop hỗ trợ."})
            if selected:
                product = selected[0]
                cases.append({"case_id": f"shop{shop_id}_catalog_policy", "business_id": shop_id,
                              "catalog_snapshot_id": shop["snapshot_id"], "catalog_product_id": product["product_id"],
                              "case_type": "catalog_plus_policy",
                              "query": f"Giá {product['name']} bao nhiêu và nếu lỗi thì shop xử lý thế nào?",
                              "sku": product["sku"], "expected_facts": {"price": product["price"]},
                              "expected_action": "answer_from_catalog_and_source",
                              "suggested_source_refs": [*_product_sources(shop, product), policy["source_ref"]],
                              "human_review": {"status": "pending", "reviewer": None, "reviewed_at": None},
                              "answer_contract": "Giá lấy từ snapshot; chính sách chỉ lấy từ tài liệu shop."})
    parts = snapshot["shops"].get("4", {})
    active_parts = [p for p in parts.get("products", []) if p["status"].casefold() == "active"]
    for category, query, missing, case_id in (
        ("Dầu nhớt", "Mình cần dầu nhớt động cơ cho xe máy, loại nào phù hợp?", "xe số hay xe tay ga", "shop4_oil_needs_vehicle_type"),
        ("Lốp và săm", "Mình cần lốp xe máy không săm, loại nào phù hợp?", "vị trí bánh và cỡ lốp", "shop4_tire_needs_position_and_size"),
        ("Lọc gió", "Mình cần lọc gió xe máy, loại nào phù hợp?", "dòng xe và đời xe", "shop4_air_filter_needs_model"),
    ):
        candidates = [p for p in active_parts
                      if category in p.get("metadata", {}).get("attributes", {}).get("category", [])]
        if category == "Dầu nhớt":
            candidates = [p for p in candidates if "động cơ" in p["name"].casefold()]
        if category == "Lốp và săm":
            candidates = [p for p in candidates if "lốp" in p["name"].casefold()]
        if len(candidates) < 2:
            continue
        candidates = candidates[:3]
        source_refs = sorted({ref for product in candidates for ref in _product_sources(parts, product)})
        cases.append({
            "case_id": case_id, "business_id": 4, "catalog_snapshot_id": parts["snapshot_id"],
            "catalog_product_ids": [p["product_id"] for p in candidates], "case_type": "clarification_required",
            "query": query, "expected_facts": {"clarification_needed": True, "missing_attribute": missing},
            "expected_action": "ask_clarification", "suggested_source_refs": source_refs,
            "human_review": {"status": "pending", "reviewer": None, "reviewed_at": None},
            "answer_contract": f"Hỏi rõ {missing} trước khi chọn sản phẩm; không khẳng định loại phù hợp khi thiếu thuộc tính."
        })
    # Keep all three shops represented and cap at a small first-round set.
    cases.sort(key=lambda c: (c["business_id"], c["case_type"], c["case_id"]))
    return cases[:TARGET_CASES]


def prepare(out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot = _snapshot()
    snapshot_path = out_dir / "shop-catalog-knowledge-snapshots-v1.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cases = _make_cases(snapshot)
    cases_path = out_dir / "rag-answer-review-suggestions-v1.jsonl"
    cases_path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")
    return snapshot_path, cases_path


def _chunk_json(chunk: RetrievedChunk) -> dict:
    return {
        "chunk_id": chunk.chunk_id, "document_id": chunk.document_id,
        "content": chunk.content, "similarity": chunk.similarity,
        "metadata": chunk.metadata, "filename": chunk.filename,
        "chunk_index": chunk.chunk_index, "ranking_score": chunk.ranking_score,
        "retrieval_scores": chunk.retrieval_scores,
    }


def _chunks_from_json(rows: list[dict]) -> list[RetrievedChunk]:
    return [RetrievedChunk(
        chunk_id=int(row["chunk_id"]), document_id=int(row["document_id"]),
        content=str(row["content"]), similarity=float(row["similarity"]),
        metadata=row.get("metadata"), filename=row.get("filename"),
        chunk_index=row.get("chunk_index"), ranking_score=row.get("ranking_score"),
        retrieval_scores=row.get("retrieval_scores") or {},
    ) for row in rows]


def _verify_snapshot_products(db, shop: dict) -> None:
    current = {
        int(row.id): _product_json(row)
        for row in db.scalars(select(Product).where(Product.business_id == shop["business_id"])).all()
    }
    frozen = {int(row["product_id"]): row for row in shop["products"]}
    if current.keys() != frozen.keys():
        raise RuntimeError(f"Catalog changed since snapshot for shop {shop['business_id']}; capture a new snapshot")
    changed = [product_id for product_id, row in frozen.items()
               if _hash(current[product_id]) != _hash(row)]
    if changed:
        raise RuntimeError(
            f"Catalog changed since snapshot for shop {shop['business_id']} (product IDs {changed[:8]}); capture a new snapshot"
        )


def _verify_snapshot_chunks(db, shop: dict, chunks: list[RetrievedChunk]) -> None:
    frozen = {
        (int(doc["document_id"]), int(chunk["chunk_index"])): chunk["content"]
        for doc in shop["documents"] for chunk in doc["chunks"]
    }
    for chunk in chunks:
        if chunk.document_id <= 0:
            continue
        expanded_ids = (chunk.metadata or {}).get("expanded_chunk_ids")
        if expanded_ids:
            source_rows = [db.get(DocumentChunk, int(chunk_id)) for chunk_id in expanded_ids]
            if any(row is None or row.document_id != chunk.document_id for row in source_rows):
                raise RuntimeError(f"Parent retrieval contains an unknown chunk for shop {shop['business_id']}")
            for row in source_rows:
                expected = frozen.get((chunk.document_id, int(row.chunk_index)))
                if expected is None or expected != row.content or row.content not in chunk.content:
                    raise RuntimeError(
                        f"Knowledge chunk changed since snapshot for shop {shop['business_id']}, chunk {row.id}; capture a new snapshot"
                    )
            continue
        expected = frozen.get((chunk.document_id, int(chunk.chunk_index))) if chunk.chunk_index is not None else None
        if expected is None and chunk.chunk_id > 0:
            row = db.get(DocumentChunk, chunk.chunk_id)
            if row is not None and row.document_id == chunk.document_id:
                expected = row.content
        if expected is None or expected != chunk.content:
            raise RuntimeError(
                f"Knowledge chunk changed since snapshot for shop {shop['business_id']}, chunk {chunk.chunk_id}; capture a new snapshot"
            )


def prepare_retrieval(snapshot_path: Path, cases_path: Path, output_path: Path) -> dict:
    """Freeze one tenant-scoped retrieval result per case for a fair A/B/C replay."""
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    schemas = _schemas()
    retrieval_config = {
        "mode": settings.RAG_RETRIEVAL_MODE, "top_k": 5, "ppr_enabled": False,
        "controller_threshold": settings.RAG_AGENTIC_RETRY_THRESHOLD,
    }
    cases_hash = _hash(cases)
    snapshot_hash = _hash(snapshot)
    prior_rows: dict[str, dict] = {}
    if output_path.exists():
        try:
            old = json.loads(output_path.read_text(encoding="utf-8"))
            if (old.get("snapshot_hash") == snapshot_hash and old.get("cases_hash") == cases_hash
                    and old.get("retrieval_config") == retrieval_config):
                prior_rows = {row["case_id"]: row for row in old.get("cases", [])}
        except (OSError, ValueError, KeyError):
            prior_rows = {}

    rows = []
    verified_shops: set[int] = set()
    payload = {
        "schema_version": 1, "status": "in_progress",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot_file": snapshot_path.name, "case_file": cases_path.name,
        "snapshot_hash": snapshot_hash, "cases_hash": cases_hash,
        "retrieval_config": retrieval_config, "cases": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        old = prior_rows.get(case["case_id"], {})
        if old.get("case_hash") == _hash(case) and old.get("retrieval_config") == retrieval_config:
            rows.append(old)
            continue
        shop = snapshot["shops"][str(case["business_id"])]
        filters = extract_query_hard_filters(case["query"])
        diagnostics: dict = {}
        started = time.perf_counter()
        with tenant_session(schemas[case["business_id"]]) as db:
            if case["business_id"] not in verified_shops:
                _verify_snapshot_products(db, shop)
                verified_shops.add(case["business_id"])
            base = retrieve(
                query=case["query"], db=db, business_id=case["business_id"], top_k=5,
                retrieval_mode=settings.RAG_RETRIEVAL_MODE, enable_ppr=False,
                hard_filters=filters, diagnostics=diagnostics,
            )
            base_ms = round((time.perf_counter() - started) * 1000, 2)
            retry_query = corrective_query(case["query"]) if retrieval_is_weak(
                base, settings.RAG_AGENTIC_RETRY_THRESHOLD,
            ) else case["query"]
            retry: list[RetrievedChunk] = []
            retry_ms = 0.0
            retry_diagnostics: dict = {}
            if retry_query != case["query"]:
                retry_started = time.perf_counter()
                retry = retrieve(
                    query=retry_query, db=db, business_id=case["business_id"], top_k=5,
                    retrieval_mode=settings.RAG_RETRIEVAL_MODE, enable_ppr=False,
                    hard_filters=filters, diagnostics=retry_diagnostics,
                )
                retry_ms = round((time.perf_counter() - retry_started) * 1000, 2)
            _verify_snapshot_chunks(db, shop, [*base, *retry])
            serving_route = None
            if case["case_type"] in {"price", "stock", "availability", "sku_exact", "unknown_sku"}:
                from app.services.auto_reply_service import _deterministic_customer_reply
                route_started = time.perf_counter()
                route = _deterministic_customer_reply(
                    db, business_id=case["business_id"], conversation_id=0,
                    query_text=case["query"], reply_metadata={},
                )
                if route is not None:
                    serving_route = {
                        "route": route[1], "answer": route[0],
                        "latency_ms": round((time.perf_counter() - route_started) * 1000, 2),
                    }
        row = {
            "case_id": case["case_id"], "case_hash": _hash(case),
            "business_id": case["business_id"], "query": case["query"],
            "retrieval_config": retrieval_config, "retrieval_query": case["query"],
            "hard_filters": filters, "base_chunks": [_chunk_json(c) for c in base],
            "base_evidence_hash": _hash([_chunk_json(c) for c in base]),
            "base_retrieval_latency_ms": base_ms, "base_diagnostics": diagnostics,
            "retry_query": retry_query if retry else None,
            "retry_chunks": [_chunk_json(c) for c in retry],
            "retry_evidence_hash": _hash([_chunk_json(c) for c in retry]),
            "retry_retrieval_latency_ms": retry_ms, "retry_diagnostics": retry_diagnostics,
            "serving_route": serving_route,
            "tenant_schema": schemas[case["business_id"]],
        }
        rows.append(row)
        payload["cases"] = rows
        payload["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"prepared_cases": len(rows), "total_cases": len(cases), "case_id": case["case_id"]}), flush=True)
    payload["status"] = "completed"
    payload["cases"] = rows
    payload["retrieval_hash"] = _hash([
        {"case_id": row["case_id"], "base_evidence_hash": row["base_evidence_hash"],
         "retry_evidence_hash": row["retry_evidence_hash"]}
        for row in rows
    ])
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _catalog_chunk(case: dict, shop: dict) -> RetrievedChunk:
    product_id = case.get("catalog_product_id")
    product = next((p for p in shop["products"] if p["product_id"] == product_id), None)
    if product:
        price = f"{int(Decimal(str(product['price']))):,}".replace(",", ".")
        status = str(product["status"]).strip().casefold()
        sale_status = "Đang bán" if status == "active" else f"Không đang bán (trạng thái: {status})"
        text = (
            "CURRENT_CRM_PRODUCT\n"
            f"SKU: {product['sku']}\nTên sản phẩm: {product['name']}\n"
            f"Trạng thái bán hiện hành: {sale_status}\nGiá hiện hành: {price} VND\n"
            f"Tồn khả dụng: {product['available_quantity']}\n"
            f"Mô tả catalog: {product.get('description') or ''}\n"
            f"Snapshot: {shop['snapshot_id']}\nFetched at: {shop['fetched_at']}"
        )
        meta = {"source": "Danh mục sản phẩm hiện hành", "source_kind": "crm_product",
                "type": "crm_product", "product_id": product["product_id"], "sku": product["sku"],
                "price": float(Decimal(str(product["price"]))),
                "available": product["available_quantity"], "status": status,
                "fetched_at": shop["fetched_at"], "availability_scope": "shop_catalog",
                "business_id": case["business_id"], "snapshot_id": shop["snapshot_id"]}
    elif case.get("catalog_product_ids"):
        wanted = set(case["catalog_product_ids"])
        candidates = [p for p in shop["products"] if p["product_id"] in wanted]
        lines = [f"Candidate products from shop snapshot {shop['snapshot_id']}:"]
        for candidate in candidates:
            attrs = candidate.get("metadata", {}).get("attributes", {})
            fit = "; ".join(str(value) for value in attrs.get("suitable_for", []))
            variants = "; ".join(str(value) for key, values in attrs.items()
                                  if key in {"sizes", "size", "colors", "color"}
                                  for value in (values if isinstance(values, list) else [values]))
            lines.append(
                f"- {candidate['name']} | SKU {candidate['sku']} | phù hợp: {fit or 'chưa khai báo'}"
                f" | biến thể: {variants or 'chưa khai báo'} | giá: {candidate['price']} VND"
                f" | còn: {candidate['available_quantity']} | trạng thái: {candidate['status']}"
            )
        lines.append("If required vehicle/model/size details are missing, ask the customer before recommending a candidate.")
        text = "\n".join(lines)
        meta = {"source": "tenant_product_catalog_snapshot", "product_ids": [p["product_id"] for p in candidates],
                "business_id": case["business_id"], "snapshot_id": shop["snapshot_id"]}
        return RetrievedChunk(0, 0, text, 1.0, meta, filename="catalog snapshot", chunk_index=0)
    elif case.get("case_type") == "unknown_sku":
        text = f"No product with exact SKU {case['sku']} exists in shop snapshot {shop['snapshot_id']}. Do not infer price or stock."
        meta = {"source": "tenant_catalog_exact_lookup", "sku": case["sku"],
                "business_id": case["business_id"], "snapshot_id": shop["snapshot_id"]}
    else:
        text = "No catalog evidence is attached to this policy-only case."
        meta = {"source": "catalog_snapshot", "business_id": case["business_id"], "snapshot_id": shop["snapshot_id"]}
    return RetrievedChunk(0, 0, text, 1.0, meta, filename="catalog snapshot", chunk_index=0)


def _normalized_price(value: object) -> str | None:
    try:
        return str(int(Decimal(str(value)).quantize(Decimal("1"))))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _automatic_fact_checks(case: dict, answer: str) -> dict:
    expected = case.get("expected_facts", {})
    claim_text = re.sub(r"\[(?:Nguồn|Source)\s+\d+\]", "", answer, flags=re.I)
    expected_price = _normalized_price(expected["price"]) if expected.get("price") is not None else None
    mentioned_prices = [re.sub(r"\D", "", value) for value in re.findall(
        r"(?<!\w)(\d[\d.,\s]*\d|\d)\s*(?:đ(?:ồng)?|vnd|₫)", claim_text, re.I,
    )]
    price_match = (
        None if expected_price is None or not mentioned_prices
        else expected_price in mentioned_prices
    )

    expected_stock = expected.get("available_quantity")
    stock_mentions = bool(re.search(
        r"(?:tồn kho|còn hàng|còn lại|số lượng|có sẵn|hiện có|hết hàng|không còn hàng|đã hết)",
        claim_text, re.I,
    ))
    stock_claims = [int(value) for value in re.findall(
        r"(?:còn(?:\s+lại|\s+hàng)?|tồn\s+kho|số\s+lượng(?:\s+khả\s+dụng|\s+còn)?|có\s+sẵn|hiện\s+có|available(?:\s+quantity)?)\D{0,24}(\d+)",
        claim_text, re.I,
    )]
    stock_match = None
    if expected_stock is not None and stock_mentions:
        stock_match = (int(expected_stock) in stock_claims) if stock_claims else None
        negative_availability = bool(re.search(
            r"hết\s+hàng|không\s+còn\s+hàng|đã\s+hết|chưa\s+có\s+sẵn", claim_text, re.I,
        ))
        positive_text = re.sub(
            r"(?:không|chưa)\s+(?:còn\s+hàng|còn\s+lại|có\s+sẵn|hiện\s+có)", "", claim_text, flags=re.I,
        )
        positive_availability = bool(re.search(r"còn\s+hàng|còn\s+lại|có\s+sẵn|hiện\s+có", positive_text, re.I))
        if int(expected_stock) == 0 and not stock_claims and negative_availability:
            stock_match = True
        if int(expected_stock) == 0 and positive_availability and not negative_availability:
            stock_match = False
        if int(expected_stock) > 0 and negative_availability:
            stock_match = False
    return {
        "wrong_price_or_stock": price_match is False or stock_match is False,
        "price_match": price_match,
        "stock_match": stock_match,
    }


def _llm_call(messages: list[dict], *, provider: str, model: str) -> tuple[str, dict]:
    started = time.perf_counter()
    if provider == "gemini":
        from app.rag.llm_caller import call_gemini
        try:
            answer, provider_usage = call_gemini(messages, model=model, include_usage=True)
        except Exception as error:
            message = str(error)
            if getattr(error, "status_code", None) == 429 or re.search(
                r"quota|rate.?limit|resource[_ ]exhausted|too many requests", message, re.I,
            ):
                raise ProviderQuotaLimit(message[:500]) from error
            raise
        return answer, {
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "prompt_tokens": provider_usage.get("prompt_tokens"),
            "completion_tokens": provider_usage.get("completion_tokens"),
            "thoughts_tokens": provider_usage.get("thoughts_tokens"),
            "total_tokens": provider_usage.get("total_tokens"),
            "provider": provider, "model": model,
            "usage_accounting": "google_genai_response_usage_metadata",
        }
    if provider != "groq":
        raise RuntimeError(f"Unsupported evaluation provider: {provider}")
    keys = settings.groq_api_keys
    if not keys:
        raise RuntimeError("Groq key is not configured in backend runtime")
    from openai import OpenAI
    client = OpenAI(api_key=keys[0], base_url="https://api.groq.com/openai/v1", max_retries=0)
    for attempt in range(8):
        try:
            response = client.chat.completions.create(
                model=model, messages=messages, temperature=0.1,
                max_completion_tokens=ANSWER_MAX_COMPLETION_TOKENS,
            )
            break
        except Exception as error:
            if getattr(error, "status_code", None) != 429 or attempt == 7:
                raise
            message = str(error)
            if re.search(r"tokens?\s+per\s+day|daily\s+token|TPD", message, re.I):
                raise ProviderQuotaLimit(message[:500]) from error
            retry_after = re.search(
                r"try again in\s+(?:(\d+(?:\.\d+)?)h)?\s*"
                r"(?:(\d+(?:\.\d+)?)m)?\s*(\d+(?:\.\d+)?)s",
                message, re.I,
            )
            if retry_after:
                hours, minutes, seconds = (float(value or 0) for value in retry_after.groups())
                delay = hours * 3600 + minutes * 60 + seconds + 1
            else:
                delay = min(2 ** (attempt + 1), 60)
            if delay > 60:
                raise ProviderQuotaLimit(f"Groq asked to wait {delay:.0f}s after HTTP 429") from error
            print(f"Groq rate limit; retrying in {delay:.0f}s (attempt {attempt + 1}/8)", flush=True)
            time.sleep(max(delay, 1))
    elapsed = (time.perf_counter() - started) * 1000
    usage = response.usage
    return response.choices[0].message.content or "", {
        "latency_ms": round(elapsed, 2), "prompt_tokens": int(usage.prompt_tokens) if usage else None,
        "completion_tokens": int(usage.completion_tokens) if usage else None,
        "total_tokens": int(usage.total_tokens) if usage else None,
        "provider": provider, "model": model,
        "finish_reason": response.choices[0].finish_reason,
        "max_completion_tokens": ANSWER_MAX_COMPLETION_TOKENS,
    }


def _find_reusable_answer(
    arms: dict[str, dict],
    candidate_arms: list[str],
    messages: list[dict],
    generation_config: dict,
) -> tuple[str, dict] | None:
    """Pair identical prompts across arms so provider sampling noise is not scored as an arm effect."""
    for name in candidate_arms:
        result = arms.get(name) or {}
        if (
            str(result.get("answer") or "").strip()
            and result.get("messages") == messages
            and result.get("generation_config") == generation_config
        ):
            return name, result
    return None


def _pair_identical_arm_outputs(case: dict, arm_order: tuple[str, ...]) -> None:
    """Normalize older runs by reusing answers whenever arms sent identical prompts."""
    arms = case.get("arms") or {}
    for arm_index, arm_name in enumerate(arm_order):
        result = arms.get(arm_name) or {}
        messages = result.get("messages")
        if not isinstance(messages, list) or not messages or not str(result.get("answer") or "").strip():
            continue
        reusable = _find_reusable_answer(
            arms, list(arm_order[:arm_index]), messages, result.get("generation_config") or {}
        )
        if not reusable:
            continue
        source_name, source = reusable
        source_answer = str(source.get("answer") or "")
        if result.get("answer") != source_answer:
            result.setdefault("unpaired_answer", result.get("answer"))
            result.setdefault("unpaired_automatic_checks", result.get("automatic_checks"))
            result.setdefault("unpaired_end_to_end_latency_ms", result.get("end_to_end_latency_ms"))
        result["answer"] = source_answer
        result["answer_empty"] = not bool(source_answer.strip())
        result["answer_generation_reused_from"] = source_name
        result["answer_generation_pairing"] = "identical_prompt_same_generation_config"
        result["usage"] = dict(source.get("usage") or {})
        generation_ms = float(
            source.get("generation_latency_ms")
            or (source.get("usage") or {}).get("latency_ms")
            or 0.0
        )
        result["generation_latency_ms"] = round(generation_ms, 2)
        result["end_to_end_latency_ms"] = round(
            float(result.get("retrieval_latency_ms") or 0.0)
            + float(result.get("controller_retry_latency_ms") or 0.0)
            + generation_ms,
            2,
        )
        citations = [int(value) for value in re.findall(
            r"\[(?:Nguồn|Source)\s+(\d+)\]", source_answer, re.I
        )]
        result["citation_references"] = citations
        result["citation_ids_in_range"] = all(
            1 <= value <= len(result.get("evidence") or []) for value in citations
        )
        result.setdefault("automatic_checks", {}).update(_automatic_fact_checks(case, source_answer))


class ProviderQuotaLimit(RuntimeError):
    pass


def run_answers(
    snapshot_path: Path,
    cases_path: Path,
    retrieval_path: Path,
    output_path: Path,
    *,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> dict:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    retrieval_cache = json.loads(retrieval_path.read_text(encoding="utf-8"))
    if retrieval_cache.get("status") != "completed":
        raise RuntimeError("Retrieval snapshot is incomplete; run prepare-retrieval first")
    if retrieval_cache.get("snapshot_hash") != _hash(snapshot) or retrieval_cache.get("cases_hash") != _hash(cases):
        raise RuntimeError("Retrieval snapshot does not match the supplied catalog snapshot and case set")
    retrieval_rows = {row["case_id"]: row for row in retrieval_cache.get("cases", [])}
    if set(retrieval_rows) != {case["case_id"] for case in cases}:
        raise RuntimeError("Retrieval snapshot case IDs do not match the case set")
    retrieval_hash = retrieval_cache.get("retrieval_hash") or _hash([
        {"case_id": row["case_id"], "base_evidence_hash": row["base_evidence_hash"],
         "retry_evidence_hash": row["retry_evidence_hash"]}
        for row in retrieval_cache.get("cases", [])
    ])
    llm_provider = (llm_provider or settings.LLM_PROVIDER).strip().casefold()
    llm_model = (llm_model or (
        settings.GEMINI_FALLBACK_MODEL if llm_provider == "gemini" else settings.LLM_MODEL
    )).strip()
    if llm_provider not in {"groq", "gemini"}:
        raise RuntimeError("Evaluation supports only Groq and Gemini providers")
    rows = []
    prior = {}
    generation_config = {
        "provider": llm_provider, "model": llm_model,
        "temperature": 0.1 if llm_provider == "groq" else "provider_default",
        "max_completion_tokens": ANSWER_MAX_COMPLETION_TOKENS if llm_provider == "groq" else None,
        "retrieval_snapshot_hash": retrieval_hash,
        "current_catalog_source": "CURRENT_CRM_PRODUCT_v1",
        "answer_harness_version": 3,
    }
    if output_path.exists():
        try:
            old = json.loads(output_path.read_text(encoding="utf-8"))
            if (old.get("snapshot_file") == snapshot_path.name and old.get("case_file") == cases_path.name
                    and old.get("retrieval_hash") == retrieval_hash):
                prior = {row["case_id"]: row for row in old.get("cases", [])}
        except (OSError, ValueError, KeyError):
            prior = {}

    def checkpoint(current: list[dict], status: str, provider_error: str | None = None) -> dict:
        payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "mode": "offline_answer_comparison_no_customer_send", "status": status,
                   "snapshot_file": snapshot_path.name, "case_file": cases_path.name, "cases": current}
        payload.update({"retrieval_file": retrieval_path.name, "retrieval_hash": retrieval_hash,
                        "generation_config": generation_config})
        if provider_error:
            payload["provider_limit"] = {"provider": llm_provider, "model": llm_model,
                                          "error": provider_error}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

    fact_types = {"price", "stock", "availability", "sku_exact", "unknown_sku"}
    provider_error = None
    for case_index, case in enumerate(cases):
        shop = snapshot["shops"][str(case["business_id"])]
        frozen = retrieval_rows[case["case_id"]]
        base_chunks = _chunks_from_json(frozen["base_chunks"])
        old_arms = prior.get(case["case_id"], {}).get("arms", {})
        arms = dict(old_arms)
        partial = {**case, "arms": arms}
        arm_order = (("B_catalog", "C_catalog_controller", "A_no_catalog")
                     if frozen.get("serving_route") else
                     ("A_no_catalog", "B_catalog", "C_catalog_controller"))
        for arm_index, arm in enumerate(arm_order):
            existing = arms.get(arm, {})
            if existing.get("generation_config") == generation_config and str(existing.get("answer") or "").strip():
                continue
            serving_route = frozen.get("serving_route") if arm != "A_no_catalog" and case["case_type"] in fact_types else None
            if provider_error and not serving_route:
                arms[arm] = {
                    "answer": "", "answer_empty": True, "status": "skipped_provider_limit",
                    "generation_config": generation_config, "usage": {"provider": llm_provider, "model": llm_model},
                    "automatic_checks": {"wrong_shop": None, **_automatic_fact_checks(case, "")},
                }
                partial["arms"] = arms
                checkpoint([*rows, partial, *({**remaining, "arms": {}} for remaining in cases[case_index + 1:])],
                           "in_progress", provider_error)
                continue
            if serving_route:
                answer = serving_route["answer"]
                messages = []
                generation_reused_from = None
                generation_ms = 0.0
                usage = {"provider": "none", "model": None, "prompt_tokens": 0,
                         "completion_tokens": 0, "total_tokens": 0}
                chunks = [_catalog_chunk(case, shop)]
                retrieval_ms = 0.0
                controller_ms = 0.0
                retry_used = False
                elapsed = float(serving_route.get("latency_ms") or 0)
                route_name = serving_route["route"]
            else:
                chunks = list(base_chunks)
                retrieval_ms = float(frozen["base_retrieval_latency_ms"])
                controller_ms = 0.0
                retry_used = False
                if arm == "C_catalog_controller" and frozen.get("retry_chunks"):
                    candidate = _chunks_from_json(frozen["retry_chunks"])
                    retry_used = True
                    controller_ms = float(frozen.get("retry_retrieval_latency_ms") or 0)
                    if evidence_quality(candidate) > evidence_quality(chunks):
                        chunks = candidate
                if arm != "A_no_catalog" and case["case_type"] != "policy":
                    chunks = [_catalog_chunk(case, shop), *chunks]
                messages = build_prompt(case["query"], chunks)
                reusable = _find_reusable_answer(
                    arms, list(arm_order[:arm_index]), messages, generation_config
                )
                generation_reused_from = reusable[0] if reusable else None
                if reusable:
                    _, source_result = reusable
                    answer = source_result["answer"]
                    usage = dict(source_result.get("usage") or {})
                    generation_ms = float(
                        source_result.get("generation_latency_ms")
                        or usage.get("latency_ms")
                        or 0.0
                    )
                else:
                    started = time.perf_counter()
                    try:
                        answer, usage = _llm_call(messages, provider=llm_provider, model=llm_model)
                    except ProviderQuotaLimit as error:
                        provider_error = str(error)
                        answer = ""
                        usage = {"provider": llm_provider, "model": llm_model,
                                 "prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
                        route_name = "provider_limit"
                        elapsed = 0.0
                        arms[arm] = {
                            "answer": answer, "answer_empty": True, "status": "provider_limit",
                            "generation_config": generation_config, "messages": messages,
                            "evidence": [{"source": c.filename, "metadata": c.metadata, "chunk_id": c.chunk_id} for c in chunks],
                            "retrieval_latency_ms": round(retrieval_ms, 2),
                            "controller_retry_latency_ms": round(controller_ms, 2),
                            "generation_latency_ms": 0.0,
                            "answer_generation_reused_from": None,
                            "retry_used": retry_used, "end_to_end_latency_ms": 0.0, "usage": usage,
                            "citation_references": [], "citation_ids_in_range": True,
                            "automatic_checks": {"wrong_shop": None, **_automatic_fact_checks(case, "")},
                        }
                        partial["arms"] = arms
                        checkpoint([*rows, partial], "in_progress", provider_error)
                        continue
                    generation_ms = float(
                        usage.get("latency_ms") or (time.perf_counter() - started) * 1000
                    )
                elapsed = retrieval_ms + controller_ms + generation_ms
                route_name = "rag_llm"
            valid_source_ids = len(chunks)
            citations = [int(v) for v in re.findall(r"\[(?:Nguồn|Source)\s+(\d+)\]", answer, re.I)]
            arms[arm] = {
                "answer": answer, "messages": messages, "generation_config": generation_config,
                "answer_empty": not bool(answer.strip()),
                "serving_route": route_name,
                "evidence": [{"source": c.filename, "metadata": c.metadata, "chunk_id": c.chunk_id} for c in chunks],
                "retrieval_latency_ms": round(retrieval_ms, 2), "controller_retry_latency_ms": round(controller_ms, 2),
                "generation_latency_ms": round(generation_ms, 2),
                "answer_generation_reused_from": generation_reused_from,
                "retry_used": retry_used, "end_to_end_latency_ms": round(elapsed, 2), "usage": usage,
                "citation_references": citations,
                "citation_ids_in_range": all(1 <= c <= valid_source_ids for c in citations),
                "citation_check_applicable": route_name == "rag_llm",
                "automatic_checks": {"wrong_shop": None, **_automatic_fact_checks(case, answer),
                                     "answer_correct": None, "citation_supported": None,
                                     "unsupported_attribute": None, "helpful_resolution": None,
                                     "clarified_when_needed": None},
            }
            partial["arms"] = arms
            checkpoint([*rows, partial], "in_progress")
        rows.append(partial)
        print(json.dumps({"completed_cases": len(rows), "total_cases": len(cases), "case_id": case["case_id"]}), flush=True)
    for case in rows:
        frozen = retrieval_rows[case["case_id"]]
        arm_order = (("B_catalog", "C_catalog_controller", "A_no_catalog")
                     if frozen.get("serving_route") else
                     ("A_no_catalog", "B_catalog", "C_catalog_controller"))
        _pair_identical_arm_outputs(case, arm_order)
        for arm_result in case["arms"].values():
            arm_result.setdefault("automatic_checks", {}).update(
                _automatic_fact_checks(case, arm_result.get("answer", ""))
            )
    arm_summary = {}
    for arm in ("A_no_catalog", "B_catalog", "C_catalog_controller"):
        all_runs = [case.get("arms", {}).get(arm, {}) for case in rows]
        runs = [run for run in all_runs if str(run.get("answer") or "").strip()]
        latencies = sorted(run["end_to_end_latency_ms"] for run in runs)
        token_values = [run["usage"].get("total_tokens") for run in runs]
        tokens_known = bool(runs) and all(isinstance(value, int) for value in token_values)
        total_tokens = sum(token_values) if tokens_known else None
        cited_runs = [run for run in runs if run["citation_references"]]
        arm_summary[arm] = {
            "cases": len(runs), "skipped_or_unavailable": len(all_runs) - len(runs),
            "p50_end_to_end_ms": round(statistics.median(latencies), 2) if latencies else None,
            "p95_end_to_end_ms": latencies[max(0, int(len(latencies) * .95 + .999999) - 1)] if latencies else None,
            "tokens": total_tokens,
            "token_usage_complete": tokens_known,
            "configured_cost_estimate": (
                round(total_tokens / 1000 * settings.AI_COST_PER_1K_TOKENS, 6)
                if tokens_known else None
            ),
            "cost_estimate_basis": (
                "generic_configured_cost_per_1k_tokens; verify against provider billing"
                if tokens_known else "token_usage_unavailable"
            ),
            "numeric_price_stock_contradictions": sum(
                run["automatic_checks"]["wrong_price_or_stock"] is True for run in runs
            ),
            "citation_refs_in_range_rate": round(sum(run["citation_ids_in_range"] for run in cited_runs) / len(cited_runs), 4) if cited_runs else None,
        }
    output = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "status": "provider_limit" if provider_error else "completed", "human_review_status": "pending",
              "mode": "offline_answer_comparison_no_customer_send", "snapshot_file": snapshot_path.name,
              "case_file": cases_path.name, "retrieval_file": retrieval_path.name,
              "retrieval_hash": retrieval_hash, "generation_config": generation_config,
              "retrieval_mode": retrieval_cache["retrieval_config"]["mode"],
              "evaluation_llm": {"provider": llm_provider, "model": llm_model},
              "ppr_enabled": False, "temperature": generation_config["temperature"],
              "controller_retry_threshold": settings.RAG_AGENTIC_RETRY_THRESHOLD,
              "controller_metrics": {
                  "cases_with_retry_candidate": sum(
                      bool(case.get("arms", {}).get("C_catalog_controller", {}).get("retry_used"))
                      for case in rows
                  ),
                  "cases_with_controller_prompt_change": sum(
                      case.get("arms", {}).get("B_catalog", {}).get("messages")
                      != case.get("arms", {}).get("C_catalog_controller", {}).get("messages")
                      for case in rows
                  ),
                  "identical_prompt_generations_reused": sum(
                      bool(run.get("answer_generation_reused_from"))
                      for case in rows for run in case.get("arms", {}).values()
                  ),
              },
              "arm_summary": arm_summary,
              "cases": rows,
              "limitations": ["Generated answers require human review for correctness and citation entailment.",
                              "The hard-error checks detect explicit numeric contradictions for price/stock; they do not certify semantic truth.",
                              "A uses the same current retrieval and prompt with catalog evidence omitted; it is a controlled no-catalog arm, not a historical binary replay."]}
    if provider_error:
        output["provider_limit"] = {"provider": llm_provider, "model": llm_model, "error": provider_error}
        output["comparison_conclusion"] = "inconclusive_provider_limit; completed answers are diagnostic only"
    else:
        output["comparison_conclusion"] = "pending human review"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--out-dir", type=Path, required=True)
    retrieve_parser = sub.add_parser("prepare-retrieval")
    retrieve_parser.add_argument("--snapshot", type=Path, required=True)
    retrieve_parser.add_argument("--cases", type=Path, required=True)
    retrieve_parser.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--snapshot", type=Path, required=True)
    run.add_argument("--cases", type=Path, required=True)
    run.add_argument("--retrieval", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--llm-provider", choices=("groq", "gemini"), default=None)
    run.add_argument("--llm-model", default=None)
    args = parser.parse_args()
    if args.command == "prepare":
        snapshot, cases = prepare(args.out_dir)
        print(json.dumps({"snapshot": str(snapshot), "cases": str(cases), "count": sum(1 for _ in cases.open(encoding="utf-8"))}))
    elif args.command == "prepare-retrieval":
        report = prepare_retrieval(args.snapshot, args.cases, args.output)
        print(json.dumps({"retrieval_snapshot": str(args.output), "cases": len(report["cases"]), "status": report["status"]}))
    else:
        report = run_answers(
            args.snapshot, args.cases, args.retrieval, args.output,
            llm_provider=args.llm_provider, llm_model=args.llm_model,
        )
        print(json.dumps({"output": str(args.output), "cases": len(report["cases"]),
                          "status": report["status"], "arms": report.get("arm_summary", {})}))


if __name__ == "__main__":
    main()
