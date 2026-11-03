"""Audit RAG source labels and compare lexical PPR variants on local tenants."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import random
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import settings
from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.models.document import Document, DocumentChunk
from app.models.industry_modules import AppointmentService
from app.models.platform_control import TenantRegistry
from app.models.recommendation_catalog import (
    RecommendationCatalogAttribute,
    RecommendationCatalogChunkMapping,
    RecommendationCatalogEntry,
)
from app.models.sales import Product
from app.rag.catalog_filters import (
    attribute_key_aliases,
    attribute_value_aliases,
    extract_query_hard_filters,
)
from app.rag.retriever import (
    RetrievedChunk,
    _diverse_candidates,
    _lexical_mmr_candidates,
    _personalized_pagerank_rerank,
    _retrieve_lexical,
    _select_retrieval_mode,
)
from app.rag.embedder import _embed_with_gemini
from app.rag import retriever as retriever_module
from app.rag.topics import infer_query_topic
from app.tenancy.schema import schema_name_for, validate_schema_name


TOP_K = 5
MMR_DIVERSITY_WEIGHT = 0.4
MMR_CANDIDATE_MULTIPLIER = 4
ACTIVE_STATES = {"active", "ready", "disabled"}
INDUSTRY_LABELS = {
    "beauty_personal_care": "Mỹ phẩm và chăm sóc cá nhân",
    "motorcycle_parts_accessories": "Phụ tùng và phụ kiện xe máy",
}
INDUSTRY_EVIDENCE = {
    "beauty_personal_care": ("Lunari/Beauty trong tài liệu và tên sản phẩm chăm sóc da",),
    "motorcycle_parts_accessories": ("Tên tài liệu phụ tùng xe máy và SKU/category trong catalog",),
}
SKU_SIZE_RE = re.compile(
    r"(?:\d+(?:[./-]\d+)*|[a-z]{1,8}\d+[a-z0-9]*(?:-[a-z0-9]+)*)"
    r"(?:\s*(?:lít|lit|ml|cl|dl|cm|mm|ah|v|inch|in))?",
    re.IGNORECASE,
)


def fold(value: object) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join("".join(char for char in raw if not unicodedata.combining(char)).split())


def normalized_value(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def active_tenants() -> list[tuple[int, str]]:
    with PlatformSessionLocal() as db:
        rows = db.scalars(select(TenantRegistry).order_by(TenantRegistry.business_id)).all()
    result = []
    for row in rows:
        schema = validate_schema_name(row.schema_name)
        if schema != schema_name_for(int(row.business_id)):
            raise ValueError(f"tenant schema mismatch for business {row.business_id}")
        if str(row.state).casefold() in ACTIVE_STATES:
            result.append((int(row.business_id), schema))
    return result


def infer_industry(documents: list[Document], chunks: list[DocumentChunk]) -> tuple[str, str, list[str]]:
    corpus = fold(" ".join(
        [doc.filename for doc in documents] + [(chunk.content or "") for chunk in chunks]
    ))
    if any(term in corpus for term in ("linh kien xe may", "phu tung xe may", "motorcycle")):
        return "motorcycle_parts_accessories", "document_and_catalog_evidence", list(INDUSTRY_EVIDENCE["motorcycle_parts_accessories"])
    if any(term in corpus for term in ("lunari", "beauty", "serum", "kem chong nang")):
        return "beauty_personal_care", "document_and_catalog_evidence", list(INDUSTRY_EVIDENCE["beauty_personal_care"])
    return "unclassified", "no_industry_setting_or_sufficient_catalog_evidence", []


def rank_metrics(expected_ids: set[int], ranked_ids: list[int]) -> dict[str, float]:
    top = ranked_ids[:TOP_K]
    hits = [int(value in expected_ids) for value in top]
    first = next((index for index, hit in enumerate(hits, start=1) if hit), None)
    dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(hits))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(len(expected_ids), TOP_K)))
    return {
        "recall_at_5": sum(hits) / max(1, len(expected_ids)),
        "mrr": 1 / first if first else 0.0,
        "ndcg_at_5": dcg / ideal if ideal else 0.0,
    }


def aggregate(rows: list[dict]) -> dict:
    if not rows:
        return {"case_count": 0, "recall_at_5": None, "mrr": None, "ndcg_at_5": None}
    return {
        "case_count": len(rows),
        **{
            key: round(sum(row[key] for row in rows) / len(rows), 6)
            for key in ("recall_at_5", "mrr", "ndcg_at_5")
        },
    }


def paired_cluster_bootstrap_delta(
    rows: list[dict],
    *,
    baseline_key: str,
    candidate_key: str,
    metric: str,
    cluster_key: str = "query_family",
    replicates: int = 5000,
    seed: int = 20261103,
) -> dict:
    """Estimate paired metric uncertainty by resampling whole query families."""
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        baseline = row.get(baseline_key)
        candidate = row.get(candidate_key)
        if not isinstance(baseline, dict) or not isinstance(candidate, dict):
            continue
        if metric not in baseline or metric not in candidate:
            continue
        group = str(row.get(cluster_key) or row.get("case_id") or "")
        if not group:
            continue
        grouped[group].append(float(candidate[metric]) - float(baseline[metric]))
    if not grouped:
        return {"case_count": 0, "cluster_count": 0, "mean_delta": None, "ci_95": None}

    families = sorted(grouped)
    observed = [delta for family in families for delta in grouped[family]]
    observed_mean = sum(observed) / len(observed)
    rng = random.Random(seed)
    samples = []
    for _ in range(max(1, replicates)):
        chosen = [families[rng.randrange(len(families))] for _ in families]
        deltas = [delta for family in chosen for delta in grouped[family]]
        samples.append(sum(deltas) / len(deltas))
    samples.sort()
    low = samples[int(0.025 * len(samples))]
    high = samples[max(0, int(0.975 * len(samples)) - 1)]
    return {
        "case_count": len(observed),
        "cluster_count": len(families),
        "baseline_method": baseline_key,
        "candidate_method": candidate_key,
        "metric": metric,
        "replicates": max(1, replicates),
        "seed": seed,
        "mean_delta": round(observed_mean, 6),
        "ci_95": [round(low, 6), round(high, 6)],
        "fraction_positive": round(sum(value > 0 for value in samples) / len(samples), 6),
        "fraction_negative": round(sum(value < 0 for value in samples) / len(samples), 6),
        "resampling": "sample query_family clusters with replacement; preserve all paired case deltas within each sampled family; average over cases",
    }


def entry_attributes(entry: RecommendationCatalogEntry) -> dict[str, list[str]]:
    values: dict[str, list[str]] = defaultdict(list)
    for attr in entry.attributes:
        values[attr.key_norm].append(attr.normalized_value)
    return values


def matches_filters(entry: RecommendationCatalogEntry, filters: dict | None) -> bool:
    if not filters:
        return True
    object_type = filters.get("object_type")
    if object_type and entry.object_type != object_type:
        return False
    sku = filters.get("sku")
    if sku:
        values = sku if isinstance(sku, (list, tuple, set)) else [sku]
        if entry.sku_norm not in {fold(value) for value in values}:
            return False
    attrs = entry_attributes(entry)
    for key, value in (filters.get("required_attributes") or {}).items():
        keys = set(attribute_key_aliases(key, value))
        values = set(attribute_value_aliases(key, value))
        if not any(attr_key in keys and attr_value in values for attr_key, attr_values in attrs.items() for attr_value in attr_values):
            return False
    return True


def _audit_entry_matches_generated_filter(
    entry: RecommendationCatalogEntry,
    case_type: str,
    filters: dict | None,
) -> bool:
    """Independently validate benchmark SKU/size/volume/color results."""
    if not filters:
        return True
    object_type = filters.get("object_type")
    if object_type and entry.object_type != object_type:
        return False
    sku = filters.get("sku")
    if sku:
        sku_values = sku if isinstance(sku, (list, tuple, set)) else [sku]
        if fold(entry.sku_norm) not in {fold(value) for value in sku_values}:
            return False

    required = filters.get("required_attributes") or {}
    attrs = entry_attributes(entry)
    if case_type == "hard_attribute_size":
        expected = required.get("size")
        key_names = {"size", "sizes", "kich_thuoc"}
        accepted_values = {fold(expected)}
    elif case_type == "hard_attribute_volume":
        expected = required.get("volume")
        if not re.search(
            r"\b\d+(?:[.,]\d+)?\s*(?:millilit(?:er|re)s?|ml|cl|dl|lit|liters?|litres?)\b",
            fold(expected),
        ):
            return False
        key_names = {"volume", "capacity", "dung_tich", "the_tich"}
        key_names.update({"size", "sizes", "kich_thuoc"})
        accepted_values = {fold(expected)}
    elif case_type == "hard_attribute_color":
        expected = required.get("color")
        key_names = {"color", "colors", "colour", "colours", "mau", "mau_sac"}
        accepted_values = {fold(value) for value in attribute_value_aliases("color", expected)}
    else:
        return matches_filters(entry, filters)

    if not expected:
        return False
    return any(
        fold(key).replace(" ", "_") in key_names
        and fold(actual) in accepted_values
        for key, values in attrs.items()
        for actual in values
    )


def _audit_chunk_matches_generated_filter(
    entries: list[RecommendationCatalogEntry],
    case_type: str,
    filters: dict | None,
) -> bool:
    """Reject unmapped or mixed-scope chunks in the independent audit oracle."""
    return bool(entries) and all(
        _audit_entry_matches_generated_filter(entry, case_type, filters)
        for entry in entries
    )


def build_cases() -> tuple[list[dict], dict[int, dict], dict[int, dict[int, list[RecommendationCatalogEntry]]], list[dict]]:
    cases: list[dict] = []
    shop_info: dict[int, dict] = {}
    shop_chunk_entries: dict[int, dict[int, list[RecommendationCatalogEntry]]] = {}
    source_audits: list[dict] = []
    tenant_rows = active_tenants()

    for business_id, schema in tenant_rows:
        with tenant_session(schema) as db:
            documents = db.scalars(
                select(Document).where(Document.business_id == business_id, Document.status == "ready")
            ).all()
            chunks = db.scalars(
                select(DocumentChunk)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(Document.business_id == business_id, Document.status == "ready")
                .order_by(DocumentChunk.id)
            ).all()
            industry, industry_source, evidence = infer_industry(documents, chunks)
            doc_by_id = {doc.id: doc for doc in documents}
            chunk_by_id = {chunk.id: chunk for chunk in chunks}
            products = {
                str(product.id): product
                for product in db.scalars(select(Product).where(Product.business_id == business_id)).all()
            }
            entries = db.scalars(
                select(RecommendationCatalogEntry)
                .where(RecommendationCatalogEntry.business_id == business_id)
                .order_by(RecommendationCatalogEntry.id)
            ).all()
            mapped: dict[int, list[RecommendationCatalogEntry]] = defaultdict(list)
            entries_by_id = {entry.id: entry for entry in entries}
            mapping_rows = db.execute(
                select(RecommendationCatalogChunkMapping.catalog_entry_id, RecommendationCatalogChunkMapping.document_chunk_id)
                .join(DocumentChunk, DocumentChunk.id == RecommendationCatalogChunkMapping.document_chunk_id)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(Document.business_id == business_id, Document.status == "ready")
            ).all()
            chunks_by_entry: dict[int, list[int]] = defaultdict(list)
            for entry_id, chunk_id in mapping_rows:
                if entry_id in entries_by_id and chunk_id in chunk_by_id:
                    chunks_by_entry[entry_id].append(int(chunk_id))
                    mapped[int(chunk_id)].append(entries_by_id[entry_id])
            shop_chunk_entries[business_id] = mapped

            shop_cases: list[dict] = []
            source_label_audit = []
            mapped_products = []
            for entry in entries:
                product = products.get(entry.external_id) if entry.object_type == "product" else None
                chunk_ids = sorted(set(chunks_by_entry.get(entry.id, [])))
                if product is None or not chunk_ids:
                    continue
                sku = fold(entry.sku_norm or product.sku or "")
                source_texts = [(chunk_by_id[chunk_id].content or "") for chunk_id in chunk_ids]
                folded_texts = [fold(text) for text in source_texts]
                name_match = any(fold(product.name) and fold(product.name) in text for text in folded_texts)
                sku_match = any(sku and re.search(r"(?<![\w-])" + re.escape(sku) + r"(?![\w-])", fold(text)) for text in source_texts)
                source_valid = bool(name_match or sku_match)
                source_product_excerpt = "\n---\n".join(
                    text for text in source_texts
                    if (fold(product.name) and fold(product.name) in fold(text))
                    or (sku and re.search(r"(?<![\w-])" + re.escape(sku) + r"(?![\w-])", fold(text)))
                )[:3000]
                source_docs = [doc_by_id.get(chunk_by_id[chunk_id].document_id) for chunk_id in chunk_ids]
                audit = {
                    "case_id": f"shop-{business_id}-product-{product.id}",
                    "business_id": business_id,
                    "industry": industry,
                    "industry_source": industry_source,
                    "industry_evidence": "; ".join(evidence),
                    "product_name": product.name,
                    "sku": sku,
                    "expected_chunk_ids": chunk_ids,
                    "query_family": f"shop-{business_id}-product-{product.id}",
                    "source_name_found": name_match,
                    "source_sku_found": sku_match,
                    "source_topically_supports_product_identity": source_valid,
                    "source_document_names": "; ".join(sorted({doc.filename for doc in source_docs if doc})),
                    "source_chunk_text": "\n---\n".join(source_texts)[:3000],
                    "label_status": "machine_verified_source_support" if source_valid else "label_failed_source_support_check",
                }
                source_label_audit.append(audit)
                mapped_products.append((entry, product, chunk_ids, audit))
                base = {
                    "business_id": business_id,
                    "industry": industry,
                    "industry_source": industry_source,
                    "label_status": "machine_verified_source_support" if source_valid else "label_failed_source_support_check",
                    "expected_chunk_ids": chunk_ids,
                    "source_evidence": audit["source_document_names"],
                    "source_chunk_text": audit["source_chunk_text"],
                    "query_family": audit["case_id"],
                    "metric_eligible": source_valid,
                }
                shop_cases.append({
                    **base,
                    "case_id": audit["case_id"],
                    "case_type": "product_info",
                    "query": f"Thông tin về sản phẩm {product.name} là gì?",
                    "hard_filters": None,
                    "expected_behavior": "Retrieve source describing this exact product; read live price and stock from CRM.",
                })
                detail_cues = (
                    "cong dung", "dac diem", "chat lieu", "kich thuoc", "tuong thich", "phu hop",
                    "dung cho", "khuyen cao", "luu y", "bao gom", "thanh phan", "dung tich",
                    "thong so", "loai da", "cach dung", "huong dan", "xuat xu", "bao hanh",
                )
                if source_valid and any(cue in fold(source_product_excerpt) for cue in detail_cues):
                    shop_cases.append({
                        **base,
                        "case_id": f"{audit['case_id']}-detail",
                        "case_type": "product_detail",
                        "query": f"Theo tài liệu, {product.name} có đặc điểm hoặc lưu ý sử dụng nào?",
                        "hard_filters": None,
                        "label_status": "source_product_identity_verified_reviewer_should_confirm_detail_scope",
                        "expected_behavior": "Retrieve product-specific documented details; do not infer missing specifications.",
                        "source_chunk_text": source_product_excerpt,
                    })
                if sku:
                    shop_cases.append({
                        **base,
                        "case_id": f"{audit['case_id']}-sku",
                        "case_type": "sku_lookup",
                        "query": f"Tìm thông tin sản phẩm có mã SKU {sku}.",
                        "hard_filters": {"sku": sku},
                        "expected_behavior": "Return only the exact SKU from this shop.",
                    })

                attributes = entry_attributes(entry)
                attribute_values = {
                    normalized_value(value)
                    for key in ("sizes", "size", "volume", "capacity")
                    for value in attributes.get(key, [])
                    if normalized_value(value)
                }
                for value in sorted(attribute_values):
                    if not SKU_SIZE_RE.fullmatch(fold(value)):
                        continue
                    query = f"Có {product.name} kích thước {value} không?"
                    extracted = extract_query_hard_filters(query)
                    required_attributes = extracted.get("required_attributes") or {}
                    attribute_key = next(
                        (key for key in ("size", "volume") if required_attributes.get(key) == value),
                        None,
                    )
                    if attribute_key is None:
                        continue
                    case_suffix = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
                    shop_cases.append({
                        **base,
                        "case_id": f"{audit['case_id']}-{attribute_key}-{case_suffix}",
                        "case_type": f"hard_attribute_{attribute_key}",
                        "query": query,
                        "hard_filters": extracted,
                        "expected_behavior": (
                            f"Match exact normalized {attribute_key} value {value} before candidate LIMIT."
                        ),
                    })
                for color in attributes.get("colors", []) + attributes.get("color", []):
                    query = f"Có {product.name} màu {color} không?"
                    extracted = extract_query_hard_filters(query)
                    if not (extracted.get("required_attributes") or {}).get("color"):
                        continue
                    shop_cases.append({
                        **base,
                        "case_id": f"{audit['case_id']}-color-{fold(color).replace(' ', '-')}",
                        "case_type": "hard_attribute_color",
                        "query": query,
                        "hard_filters": extracted,
                        "expected_behavior": f"Match the exact normalized color {color} before candidate LIMIT.",
                    })

            # Source-labelled policy cases: each answer comes from a chunk whose text contains the fact.
            policy_specs = []
            if industry == "beauty_personal_care":
                policy_specs = [
                    ("Đơn hàng tỉnh dự kiến giao trong mấy ngày?", "đơn hàng tỉnh được giao dự kiến"),
                    ("Shop hỗ trợ những hình thức thanh toán nào?", "hỗ trợ thanh toán khi nhận hàng"),
                    ("Khách có thể yêu cầu đổi hàng giao sai trong bao lâu?", "trong vòng 7 ngày"),
                    ("Khách mới nên bắt đầu quy trình chăm sóc da bằng gì?", "khách mới nên bắt đầu với"),
                    ("Da nhạy cảm nên thử sản phẩm trên vùng nào trước?", "thử sản phẩm trên vùng da nhỏ"),
                    ("Phí giao hàng hiện trước hay sau khi xác nhận đơn?", "phí giao hàng được hiển thị trước khi xác nhận đơn"),
                    ("Khi xin đổi hàng hư hỏng, khách cần giữ gì và gửi gì?", "sản phẩm đổi trả phải còn nguyên tem"),
                    ("Đơn nội thành dự kiến giao trong bao lâu?", "đơn hàng nội thành được giao dự kiến trong 1-2 ngày làm việc"),
                    ("Trong quy trình cơ bản, serum dùng buổi nào và kem chống nắng dùng ban ngày hay ban đêm?", "serum vitamin c vào buổi tối"),
                    ("Khi ở ngoài trời, sau bao lâu nên thoa lại Daily Shield?", "nên thoa lại sau mỗi 2-3 giờ"),
                    ("Sữa rửa mặt dịu nhẹ phù hợp với loại da nào?", "phù hợp với da thường và da nhạy cảm"),
                    ("Ngân sách dưới 500.000 đồng có thể chọn những sản phẩm nào?", "khách có ngân sách dưới 500.000 đồng có thể chọn"),
                    ("Combo chăm sóc da cơ bản gồm gì và giá combo là bao nhiêu?", "giá combo 799.000 đồng"),
                    ("Khi yêu cầu hỗ trợ đổi trả, khách cần cung cấp thông tin nào?", "liên hệ cskh kèm mã đơn hàng"),
                ]
            elif industry == "motorcycle_parts_accessories":
                policy_specs = [
                    ("Trước khi xác nhận phụ tùng vừa xe, cần hỏi những thông tin nào?", "trước khi xác nhận linh kiện"),
                    ("Phí giao hàng có mức cố định trong tài liệu không?", "phí giao hàng phụ thuộc"),
                    ("Ảnh biên lai có chứng minh shop đã nhận chuyển khoản không?", "ảnh biên lai"),
                    ("Điều kiện xử lý khi shop giao sai SKU là gì?", "giao sai sku"),
                    ("Những trường hợp nào cần chuyển nhân viên?", "chuyển nhân viên khi khách"),
                    ("Tài liệu có thể dùng để xác nhận giá và tồn kho hiện tại không?", "danh mục, giá hiện hành"),
                    ("Chỉ thấy tên hãng trên món phụ tùng có đủ xác nhận hàng chính hãng không?", "tên hãng trên sản phẩm chỉ là tên mặt hàng"),
                    ("Ảnh khách gửi có đủ để xác nhận phụ tùng lắp vừa xe không?", "ảnh chỉ giúp nhận diện sơ bộ"),
                    ("Nếu xe có dấu hiệu lỗi phanh thì nên hướng dẫn khách thế nào?", "khuyên ngừng chạy xe và đưa thợ kiểm tra"),
                    ("Có nên áp một lịch thay phụ tùng cố định cho mọi xe không?", "không đưa ra lịch thay cố định"),
                    ("Bot có tự thêm phụ tùng mua kèm vào đơn của khách không?", "không tự thêm sku vào đơn"),
                    ("Có thể tự hứa đơn nào cũng giao trong ngày không?", "không tự hứa giao trong ngày"),
                    ("Có thể tự cam kết đổi hoặc hoàn tiền khi khách báo sai mã không?", "không tự cam kết được đổi hoặc hoàn tiền"),
                    ("Khi tài liệu cũ đã được thay thế thì xử lý thế nào?", "không để hai bản mâu thuẫn cùng ở trạng thái sẵn sàng"),
                    ("Shop có nhận sửa chữa, lắp đặt hoặc chẩn đoán hỏng xe từ xa không?", "không nhận sửa chữa, lắp đặt hoặc chẩn đoán hư hỏng từ xa"),
                    ("Shop có thể tự nhận là đại lý ủy quyền của hãng không?", "không tự nhận là đại lý ủy quyền"),
                    ("Cần làm gì để xác minh nguồn gốc hàng chính hãng?", "nguồn gốc/chứng từ thực tế phải được nhân viên kiểm tra"),
                    ("Nếu ảnh mã phụ tùng bị mờ hoặc không thấy mã thì nên yêu cầu khách làm gì?", "nếu ảnh mờ hoặc không thấy mã"),
                    ("Khi chọn nhớt động cơ, cần đối chiếu thông tin nào của xe?", "chỉ tư vấn nếu sách xe chấp nhận"),
                    ("Nhớt láp có thể dùng thay nhớt động cơ xe tay ga không?", "không tráo với nhớt láp"),
                    ("Hai mã bugi XM-BUGI-CR7HSA và XM-BUGI-CPR8EA9 có được coi là thay thế cho nhau không?", "không nói chúng thay thế cho nhau"),
                    ("Lọc gió Sirius FI có đồng nghĩa với loại Sirius dùng chế hòa khí không?", "sirius fi không đồng nghĩa sirius dùng chế hòa khí"),
                    ("Dầu phanh DOT 4 có dùng cho phanh đùm cơ không?", "chỉ dùng cho hệ thống thủy lực yêu cầu dot 4"),
                    ("Giá trong CRM đã bao gồm công lắp và phí vận chuyển chưa?", "giá bán chưa tự bao gồm công lắp, phí vận chuyển"),
                    ("Nếu số khả dụng bằng 0, shop có nhận cọc để giữ hàng không?", "không hứa giao ngay hay nhận cọc để giữ món"),
                    ("Điều kiện nào cần đúng trước khi gợi ý mua kèm má phanh và dầu phanh?", "má phanh với dầu phanh chỉ khi xe dùng phanh thủy lực"),
                    ("Khi gợi ý sên cùng bộ nhông dĩa cần lưu ý gì?", "sên với bộ nhông dĩa phải giải thích món lẻ và bộ có thể trùng nhau"),
                    ("Có nên luôn gợi ý mua lốp kèm săm không?", "lốp với săm chỉ khi xe/vành dùng săm"),
                    ("Có nên gợi ý dầu nhớt khác chuẩn chỉ vì mặt hàng đó đang còn tồn không?", "không gợi ý dầu nhớt khác chuẩn chỉ vì đang còn tồn"),
                    ("Bot có được tự giảm giá hoặc áp khuyến mãi chưa cấu hình không?", "không tự giảm giá hoặc áp khuyến mãi chưa cấu hình"),
                    ("Khi giao sai SKU hoặc hàng lỗi lúc mở gói, cần ghi nhận những gì?", "ghi nhận mã đơn, ảnh nhãn bao bì và ảnh tình trạng sản phẩm"),
                    ("Hàng đã lắp hoặc đã sử dụng có thể kết luận đổi trả chỉ qua chat không?", "hàng đã lắp, sử dụng hoặc liên quan an toàn phải được kiểm tra thực tế"),
                    ("Có thể thông báo thời hạn bảo hành của hãng khi chưa có chứng từ lô hàng không?", "không tự công bố thời hạn bảo hành của hãng nếu chưa có chứng từ"),
                    ("Không được yêu cầu khách gửi những thông tin nhạy cảm nào qua chat?", "không yêu cầu mật khẩu, otp, thông tin thẻ hoặc mã cvv qua chat"),
                    ("Khi nào ứng dụng mới được gửi QR hoặc số tiền chuyển khoản cho khách?", "chỉ gửi qr/số tiền chuyển khoản nếu ứng dụng đã có bảng kê hợp lệ"),
                    ("Nếu khách đặt hai món, cần tính tổng tiền theo cách nào?", "nếu khách muốn hai món, cộng giá từ crm theo số lượng"),
                ]
            for policy_index, (query, source_phrase) in enumerate(policy_specs, start=1):
                needle = fold(source_phrase)
                match_chunk = next((chunk for chunk in chunks if needle in fold(chunk.content)), None)
                if match_chunk is None:
                    continue
                doc = doc_by_id.get(match_chunk.document_id)
                shop_cases.append({
                    "case_id": f"shop-{business_id}-policy-{policy_index}",
                    "business_id": business_id,
                    "industry": industry,
                    "industry_source": industry_source,
                    "case_type": "policy_faq",
                    "query": query,
                    "query_family": f"shop-{business_id}-policy-{policy_index}",
                    "expected_chunk_ids": [int(match_chunk.id)],
                    "hard_filters": None,
                    "metric_eligible": True,
                    "label_status": "source_phrase_verified_reviewer_should_confirm_answer_scope",
                    "expected_behavior": "Use cited policy source; do not infer live price or stock from this text.",
                    "source_evidence": doc.filename if doc else "",
                    "source_chunk_text": (match_chunk.content or "")[:3000],
                })

            shop_info[business_id] = {
                "business_id": business_id,
                "schema_name": schema,
                "industry": industry,
                "industry_display": INDUSTRY_LABELS.get(industry),
                "industry_source": industry_source,
                "industry_evidence": evidence,
                "mapped_product_case_count": len(mapped_products),
                "validated_product_source_count": sum(row[3]["source_topically_supports_product_identity"] for row in mapped_products),
                "failed_product_source_count": sum(not row[3]["source_topically_supports_product_identity"] for row in mapped_products),
                "document_count": len(documents),
                "appointment_service_count": len(db.scalars(select(AppointmentService.id).where(AppointmentService.business_id == business_id)).all()),
                "catalog_type_counts": {
                    kind: sum(entry.object_type == kind for entry in entries)
                    for kind in ("product", "service", "rental")
                },
                "case_count": len(shop_cases),
            }
            source_audits.extend(source_label_audit)
            cases.extend(shop_cases)

            # Cases that should abstain or ask a clarification, rather than invent a gold chunk.
            if industry == "beauty_personal_care":
                ambiguous = [
                    ("Da tôi hợp sản phẩm nào?", "Ask skin type, concern, sensitivity, and budget; do not diagnose."),
                    ("Tư vấn giúp tôi một món phù hợp.", "Ask what the customer needs before choosing a product."),
                ]
            elif industry == "motorcycle_parts_accessories":
                ambiguous = [
                    ("Món này có lắp vừa xe của tôi không?", "Ask make/model/year/version and old part code or photo; do not confirm fit."),
                    ("Xe khó nổ, thay bugi là hết đúng không?", "Do not diagnose; explain multiple causes and hand off when needed."),
                    ("Nhớt nào tốt nhất cho xe tôi?", "Ask exact bike and manual/specification before recommending."),
                    ("Phí giao hàng của tôi bao nhiêu?", "Ask delivery address or request a live shipping quote."),
                ]
            else:
                ambiguous = []
            for index, (query, behavior) in enumerate(ambiguous, start=1):
                cases.append({
                    "case_id": f"shop-{business_id}-ambiguous-{index}",
                    "business_id": business_id,
                    "industry": industry,
                    "industry_source": industry_source,
                    "case_type": "ambiguous_or_missing_context",
                    "query": query,
                    "expected_chunk_ids": [],
                    "hard_filters": None,
                    "metric_eligible": False,
                    "label_status": "answer_behavior_review_only_no_retrieval_gold",
                    "expected_behavior": behavior,
                    "source_evidence": "",
                    "source_chunk_text": "",
                })

            # Explicit exact-SKU abstention probes; no positive label is fabricated.
            if mapped_products:
                unknown_sku = f"SMH-UNKNOWN-{business_id}-999999"
                cases.append({
                    "case_id": f"shop-{business_id}-unknown-sku",
                    "business_id": business_id,
                    "industry": industry,
                    "industry_source": industry_source,
                    "case_type": "no_answer_unknown_sku",
                    "query": f"Tìm thông tin SKU {unknown_sku}.",
                    "expected_chunk_ids": [],
                    "hard_filters": {"sku": unknown_sku},
                    "metric_eligible": False,
                    "label_status": "negative_probe_expect_no_match",
                    "expected_behavior": "Return no product match and ask the user to check the SKU; no cross-shop fallback.",
                    "source_evidence": "",
                    "source_chunk_text": "",
                })

            # Coverage probes intentionally distinguish an empty catalog from a failed retrieval.
            for object_type in ("service", "rental"):
                if shop_info[business_id]["catalog_type_counts"][object_type] == 0:
                    cases.append({
                        "case_id": f"shop-{business_id}-{object_type}-catalog-empty",
                        "business_id": business_id,
                        "industry": industry,
                        "industry_source": industry_source,
                        "case_type": f"coverage_empty_{object_type}",
                        "query": f"Shop có {object_type} nào đang bán/cho thuê không?",
                        "expected_chunk_ids": [],
                        "hard_filters": {"object_type": object_type},
                        "metric_eligible": False,
                        "label_status": "coverage_probe_no_canonical_catalog_entries",
                        "expected_behavior": "Do not claim availability; clearly say the shop has no canonical entries yet or route to staff.",
                        "source_evidence": "",
                        "source_chunk_text": "",
                    })

    return cases, shop_info, shop_chunk_entries, source_audits


def edge_reasons(left: RetrievedChunk, right: RetrievedChunk) -> list[dict]:
    reasons = []
    a, b = left.metadata or {}, right.metadata or {}
    for key in ("product_id", "sku"):
        if a.get(key) is not None and str(a.get(key)).strip().casefold() == str(b.get(key, "")).strip().casefold():
            reasons.append({"type": f"same_{key}", "weight": 3.0})
    if left.document_id == right.document_id and a.get("parent_id") is not None and str(a.get("parent_id")) == str(b.get("parent_id")):
        reasons.append({"type": "same_document_parent", "weight": 2.0})
    if left.document_id == right.document_id and left.chunk_index is not None and right.chunk_index is not None and abs(int(left.chunk_index) - int(right.chunk_index)) == 1:
        reasons.append({"type": "adjacent_chunk", "weight": 0.35})
    return reasons


def constrained_ppr(candidates: list[RetrievedChunk], chunk_entries: dict[int, list[RecommendationCatalogEntry]]) -> list[RetrievedChunk]:
    """Offline ablation: exact catalog product/SKU edges only, blended 85/15 with BM25 order."""
    if len(candidates) < 2:
        return candidates
    clone = copy.deepcopy(candidates)
    for item in clone:
        matches = chunk_entries.get(item.chunk_id, [])
        if matches:
            entry = matches[0]
            item.metadata = {"product_id": str(entry.id), "sku": entry.sku_norm}
        else:
            item.metadata = {}
        item.chunk_index = None
    scores = [item.ranking_score if item.ranking_score is not None else item.similarity for item in clone]
    ppr = _personalized_pagerank_rerank(clone, scores)
    ppr_rank = {item.chunk_id: index for index, item in enumerate(ppr)}
    base_rank = {item.chunk_id: index for index, item in enumerate(candidates)}
    count = max(1, len(candidates) - 1)
    combined = {
        item.chunk_id: 0.85 * (1 - base_rank[item.chunk_id] / count)
        + 0.15 * (1 - ppr_rank.get(item.chunk_id, base_rank[item.chunk_id]) / count)
        for item in candidates
    }
    return sorted(candidates, key=lambda item: (-combined[item.chunk_id], base_rank[item.chunk_id]))


def evaluate(
    output_dir: Path,
    prior_cases_path: Path | None,
    *,
    with_gemini_embeddings: bool = False,
    require_embedding_cache: bool = False,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    cases, shops, chunk_entries_by_shop, source_audits = build_cases()
    unique_cases = {}
    for case in cases:
        case_key = (int(case["business_id"]), str(case["case_id"]))
        existing = unique_cases.get(case_key)
        if existing is not None and existing != case:
            raise ValueError(f"Conflicting duplicate evaluation case {case_key!r}")
        unique_cases.setdefault(case_key, case)
    duplicate_case_rows_removed = len(cases) - len(unique_cases)
    cases = list(unique_cases.values())
    unique_case_counts = defaultdict(int)
    for case in cases:
        unique_case_counts[int(case["business_id"])] += 1
    for business_id, shop in shops.items():
        shop["case_count"] = unique_case_counts[int(business_id)]
    results = []
    by_method: dict[str, list[dict]] = defaultdict(list)
    by_shop_type: dict[str, dict[str, dict[str, list[dict]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    source_rows = []
    label_failures = []
    ppr_diagnostics = []
    dense_retrieval_modes: dict[str, int] = defaultdict(int)
    dense_fallback_stages: dict[str, int] = defaultdict(int)
    auto_route_counts: dict[str, int] = defaultdict(int)
    embedding_query_count = 0
    embedding_api_calls = 0
    embedding_cache_hit = False
    hard_filter_violations = CounterLike()
    hard_filter_leakage_by_method = defaultdict(
        lambda: {"filtered_case_count": 0, "returned_chunk_count": 0, "leakage_chunk_count": 0}
    )
    hard_filter_audit = defaultdict(lambda: {"case_count": 0, "gold_hit_cases": 0, "gold_miss_cases": 0, "leakage_chunk_count": 0})
    abstention = defaultdict(lambda: {"probe_count": 0, "false_positive_count": 0, "returned_ids": []})

    old_cases = {}
    if prior_cases_path and prior_cases_path.exists():
        for row in (json.loads(line) for line in prior_cases_path.read_text(encoding="utf-8").splitlines() if line.strip()):
            case_key = row.get("id") or row.get("case_id")
            if case_key:
                old_cases[str(case_key)] = row

    query_embeddings: dict[str, list[float]] = {}
    if with_gemini_embeddings:
        if settings.EMBEDDING_PROVIDER.strip().casefold() != "gemini":
            raise ValueError("Fresh dense evaluation requires EMBEDDING_PROVIDER=gemini.")
        unique_queries = list(dict.fromkeys(
            case["query"] for case in cases
            if case.get("metric_eligible") and case.get("expected_chunk_ids")
        ))
        query_hashes = {
            str(index): hashlib.sha256(query.encode("utf-8")).hexdigest()
            for index, query in enumerate(unique_queries)
        }
        cache_path = output_dir / ".query-embeddings.json"
        cached_by_hash = {}
        if cache_path.exists():
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                cache.get("model") == settings.EMBEDDING_MODEL
                and cache.get("dimension") == settings.EMBEDDING_DIMENSION
            ):
                cached_by_hash = {
                    digest: cache["vectors"][index]
                    for index, digest in cache.get("query_hashes", {}).items()
                    if index in cache.get("vectors", {})
                }
        query_embeddings = {
            query: cached_by_hash[digest]
            for query, digest in zip(unique_queries, query_hashes.values())
            if digest in cached_by_hash
        }
        embedding_cache_hit = bool(query_embeddings)
        missing_queries = [query for query in unique_queries if query not in query_embeddings]
        if missing_queries and require_embedding_cache:
            raise ValueError(
                f"Embedding cache is missing {len(missing_queries)} unique queries; API calls are disabled."
            )
        if missing_queries:
            vectors = []
            batch_size = 80
            for start in range(0, len(missing_queries), batch_size):
                if start:
                    time.sleep(62)
                batch = missing_queries[start:start + batch_size]
                batch_vectors = _embed_with_gemini(
                    batch,
                    settings.EMBEDDING_MODEL,
                    task_type="RETRIEVAL_QUERY",
                )
                vectors.extend(batch_vectors)
                embedding_api_calls += 1
            if len(vectors) != len(missing_queries):
                raise ValueError("Gemini returned an unexpected number of evaluation query embeddings.")
            if any(len(vector) != settings.EMBEDDING_DIMENSION for vector in vectors):
                raise ValueError("Gemini query vector dimension does not match EMBEDDING_DIMENSION.")
            query_embeddings.update(zip(missing_queries, vectors))
            cache_path.write_text(json.dumps({
                "model": settings.EMBEDDING_MODEL,
                "dimension": settings.EMBEDDING_DIMENSION,
                "query_hashes": query_hashes,
                "vectors": {str(index): query_embeddings[query] for index, query in enumerate(unique_queries)},
            }), encoding="utf-8")
        embedding_cache_hits = len(unique_queries) - len(missing_queries)
        embedding_cache_misses = len(missing_queries)
        embedding_query_count = len(unique_queries)

    for business_id, schema in active_tenants():
        shop_cases = [case for case in cases if case["business_id"] == business_id]
        chunk_entries = chunk_entries_by_shop.get(business_id, {})
        with tenant_session(schema) as db:
            for case in shop_cases:
                filters = case.get("hard_filters")
                query_topic = infer_query_topic(case["query"])
                lexical = _retrieve_lexical(
                    case["query"], db, 50, business_id=business_id,
                    query_topic=query_topic, hard_filters=filters,
                )
                base_ids = [int(item.chunk_id) for item in lexical]
                base_top = base_ids[:TOP_K]
                bm25_best_score = max((float(item.similarity or 0.0) for item in lexical), default=0.0)
                mmr_candidate_ids = [
                    int(item.chunk_id)
                    for item in lexical[:max(TOP_K, TOP_K * MMR_CANDIDATE_MULTIPLIER)]
                ]
                mmr_top = _lexical_mmr_candidates(
                    lexical, TOP_K, diversity_weight=MMR_DIVERSITY_WEIGHT,
                    max_per_document=4 if query_topic == "products" else 2,
                )
                mmr_ids = [int(item.chunk_id) for item in mmr_top]
                current = _diverse_candidates(
                    _personalized_pagerank_rerank(copy.deepcopy(lexical), [
                        item.ranking_score if item.ranking_score is not None else item.similarity
                        for item in lexical
                    ]), TOP_K,
                    max_per_document=4 if query_topic == "products" else 2,
                )
                current_ids = [int(item.chunk_id) for item in current[:TOP_K]]
                constrained = _diverse_candidates(
                    constrained_ppr(lexical, chunk_entries), TOP_K,
                    max_per_document=4 if query_topic == "products" else 2,
                )
                constrained_ids = [int(item.chunk_id) for item in constrained[:TOP_K]]
                filter_result_ids = {
                    "bm25_candidates": base_ids,
                    "bm25_mmr_top5": mmr_ids,
                    "bm25_current_ppr_top5": current_ids,
                    "bm25_exact_entity_ppr_85_15_top5": constrained_ids,
                }
                expected = {int(value) for value in case.get("expected_chunk_ids", [])}
                eligible = bool(case.get("metric_eligible") and expected)
                row = {
                    "case_id": case["case_id"], "business_id": business_id,
                    "industry": case["industry"], "case_type": case["case_type"],
                    "query_family": case.get("query_family", case["case_id"]),
                    "query": case["query"], "expected_chunk_ids": sorted(expected),
                    "bm25_top_chunk_ids": base_top,
                    "bm25_best_candidate_score": bm25_best_score,
                    "bm25_mmr_candidate_chunk_ids": mmr_candidate_ids,
                    "bm25_mmr_top_chunk_ids": mmr_ids,
                    "bm25_current_ppr_top_chunk_ids": current_ids,
                    "bm25_exact_entity_ppr_85_15_top_chunk_ids": constrained_ids,
                    "hard_filters": filters,
                    "label_status": case["label_status"],
                    "metric_eligible": eligible,
                }
                if eligible:
                    row["bm25"] = rank_metrics(expected, base_top)
                    row["bm25_mmr"] = rank_metrics(expected, mmr_ids)
                    row["bm25_current_ppr"] = rank_metrics(expected, current_ids)
                    row["bm25_exact_entity_ppr_85_15"] = rank_metrics(expected, constrained_ids)
                    for method in ("bm25", "bm25_mmr", "bm25_current_ppr", "bm25_exact_entity_ppr_85_15"):
                        by_method[method].append(row[method])
                        by_shop_type[str(business_id)][case["case_type"]][method].append(row[method])
                        by_shop_type[f"type:{case['case_type']}"][str(business_id)][method].append(row[method])

                if case["case_type"].startswith("coverage_empty_") or case["case_type"] == "no_answer_unknown_sku":
                    bucket = abstention[case["case_type"]]
                    bucket["probe_count"] += 1
                    bucket["false_positive_count"] += bool(base_top)
                    if base_top:
                        bucket["returned_ids"].append({"case_id": case["case_id"], "ids": base_top})

                if filters and case.get("metric_eligible"):
                    audit = hard_filter_audit[case["case_type"]]
                    audit["case_count"] += 1
                    if expected.intersection(base_ids):
                        audit["gold_hit_cases"] += 1
                    else:
                        audit["gold_miss_cases"] += 1

                if case["case_type"] in {"product_info", "product_detail"} and expected:
                    bm25_rank = {chunk_id: index + 1 for index, chunk_id in enumerate(base_ids)}
                    ppr_all = _personalized_pagerank_rerank(copy.deepcopy(lexical), [item.ranking_score if item.ranking_score is not None else item.similarity for item in lexical])
                    ppr_all = _diverse_candidates(ppr_all, len(ppr_all), max_per_document=4 if query_topic == "products" else 2)
                    ppr_rank = {int(item.chunk_id): index + 1 for index, item in enumerate(ppr_all)}
                    dropped = [chunk_id for chunk_id in expected if bm25_rank.get(chunk_id, 999) <= TOP_K and ppr_rank.get(chunk_id, 999) > TOP_K]
                    promoted = [chunk_id for chunk_id in ppr_rank if ppr_rank[chunk_id] <= TOP_K and bm25_rank.get(chunk_id, 999) > TOP_K]
                    if dropped or promoted:
                        items_by_id = {int(item.chunk_id): item for item in lexical}
                        promotions = []
                        for promoted_id in promoted:
                            promoted_item = items_by_id.get(promoted_id)
                            linked = []
                            if promoted_item:
                                for peer_id in base_top:
                                    peer = items_by_id.get(peer_id)
                                    if peer:
                                        reasons = edge_reasons(promoted_item, peer)
                                        if reasons:
                                            linked.append({"peer_chunk_id": peer_id, "reasons": reasons})
                            promotions.append({"chunk_id": promoted_id, "bm25_rank": bm25_rank.get(promoted_id), "ppr_rank": ppr_rank[promoted_id], "connected_to_initial_top5": linked})
                        ppr_diagnostics.append({
                            "diagnostic_kind": "fresh_lexical_ppr_diagnostic",
                            "case_id": case["case_id"], "business_id": business_id,
                            "query": case["query"], "expected_chunk_ids_dropped_from_top5": dropped,
                            "expected_chunk_ranks": [{"chunk_id": chunk_id, "bm25_rank": bm25_rank.get(chunk_id), "current_ppr_rank": ppr_rank.get(chunk_id)} for chunk_id in expected],
                            "promoted_into_top5": promotions,
                        })

                if case["case_type"] == "product_info":
                    prior = old_cases.get(case["case_id"])
                    if prior and prior.get("query") == case["query"] and [int(x) for x in prior.get("expected_chunk_ids", [])] == sorted(expected):
                        row["prior_gemini_hybrid_no_ppr"] = prior.get("gemini_bm25_rrf_no_ppr")
                        row["prior_gemini_hybrid_ppr"] = prior.get("gemini_bm25_rrf_ppr")
                        row["prior_hybrid_labels_match_current"] = True
                        prior_top_ids = [int(value) for value in prior.get("gemini_bm25_rrf_no_ppr_top_chunk_ids", [])]
                        prior_chunks = {}
                        if prior_top_ids:
                            chunk_rows = db.execute(
                                select(DocumentChunk, Document.filename)
                                .join(Document, Document.id == DocumentChunk.document_id)
                                .where(Document.business_id == business_id, DocumentChunk.id.in_(prior_top_ids))
                            ).all()
                            for chunk, filename in chunk_rows:
                                prior_chunks[int(chunk.id)] = RetrievedChunk(
                                    chunk_id=int(chunk.id), document_id=int(chunk.document_id),
                                    content=chunk.content or "", similarity=0.0,
                                    metadata=chunk.metadata_ if isinstance(chunk.metadata_, dict) else {},
                                    filename=filename, chunk_index=chunk.chunk_index,
                                )
                        prior_candidates = []
                        for rank, chunk_id in enumerate(prior_top_ids, start=1):
                            chunk = prior_chunks.get(chunk_id)
                            if chunk:
                                # The previous no-PPR order is the base ranking; preserve it as reciprocal rank.
                                chunk.ranking_score = 1 / (60 + rank)
                                chunk.similarity = chunk.ranking_score
                                prior_candidates.append(chunk)
                        hybrid_limited_ppr = _diverse_candidates(
                            constrained_ppr(prior_candidates, chunk_entries), TOP_K,
                            max_per_document=4,
                        )
                        hybrid_limited_ids = [int(item.chunk_id) for item in hybrid_limited_ppr]
                        row["prior_gemini_hybrid_exact_entity_ppr_85_15"] = rank_metrics(expected, hybrid_limited_ids)
                        row["prior_gemini_hybrid_exact_entity_ppr_85_15_top_chunk_ids"] = hybrid_limited_ids
                        by_method["prior_gemini_hybrid_top5_exact_entity_ppr_85_15"].append(row["prior_gemini_hybrid_exact_entity_ppr_85_15"])
                        by_shop_type[str(business_id)][case["case_type"]]["prior_gemini_hybrid_top5_exact_entity_ppr_85_15"].append(row["prior_gemini_hybrid_exact_entity_ppr_85_15"])
                        by_shop_type[f"type:{case['case_type']}"][str(business_id)]["prior_gemini_hybrid_top5_exact_entity_ppr_85_15"].append(row["prior_gemini_hybrid_exact_entity_ppr_85_15"])
                        for method, key in (("prior_gemini_hybrid_no_ppr", "gemini_bm25_rrf_no_ppr"), ("prior_gemini_hybrid_ppr", "gemini_bm25_rrf_ppr")):
                            if isinstance(prior.get(key), dict):
                                by_shop_type[str(business_id)][case["case_type"]][method].append(prior[key])
                                by_shop_type[f"type:{case['case_type']}"][str(business_id)][method].append(prior[key])
                        previous_ppr_ids = [int(value) for value in prior.get("gemini_bm25_rrf_ppr_top_chunk_ids", [])]
                        previous_ppr_metrics = prior.get("gemini_bm25_rrf_ppr") or {}
                        no_ppr_metrics = prior.get("gemini_bm25_rrf_no_ppr") or {}
                        if previous_ppr_metrics.get("ndcg_at_5", 0) < no_ppr_metrics.get("ndcg_at_5", 0):
                            hybrid_chunks = dict(prior_chunks)
                            missing_ids = sorted((set(previous_ppr_ids) | set(expected)) - set(hybrid_chunks))
                            if missing_ids:
                                extra_rows = db.execute(
                                    select(DocumentChunk, Document.filename)
                                    .join(Document, Document.id == DocumentChunk.document_id)
                                    .where(Document.business_id == business_id, DocumentChunk.id.in_(missing_ids))
                                ).all()
                                for chunk, filename in extra_rows:
                                    hybrid_chunks[int(chunk.id)] = RetrievedChunk(
                                        chunk_id=int(chunk.id), document_id=int(chunk.document_id),
                                        content=chunk.content or "", similarity=0.0,
                                        metadata=chunk.metadata_ if isinstance(chunk.metadata_, dict) else {},
                                        filename=filename, chunk_index=chunk.chunk_index,
                                    )
                            baseline_ranks = {chunk_id: rank for rank, chunk_id in enumerate(prior_top_ids, start=1)}
                            ppr_ranks = {chunk_id: rank for rank, chunk_id in enumerate(previous_ppr_ids, start=1)}
                            promoted_ids = [chunk_id for chunk_id in previous_ppr_ids if chunk_id not in set(prior_top_ids)]
                            promoted_details = []
                            for promoted_id in promoted_ids:
                                item = hybrid_chunks.get(promoted_id)
                                peers = []
                                if item:
                                    for peer_id in prior_top_ids:
                                        peer = hybrid_chunks.get(peer_id)
                                        if peer:
                                            reasons = edge_reasons(item, peer)
                                            if reasons:
                                                peers.append({"peer_chunk_id": peer_id, "reasons": reasons})
                                promoted_details.append({"chunk_id": promoted_id, "ppr_rank": ppr_ranks[promoted_id], "edges_to_no_ppr_top5": peers})
                            ppr_diagnostics.append({
                                "diagnostic_kind": "historical_dense_hybrid_ppr_degradation",
                                "case_id": case["case_id"], "business_id": business_id,
                                "query": case["query"], "expected_chunk_ids": sorted(expected),
                                "expected_ranks_no_ppr_top5": [{"chunk_id": value, "rank": baseline_ranks.get(value)} for value in expected],
                                "expected_ranks_ppr_top5": [{"chunk_id": value, "rank": ppr_ranks.get(value)} for value in expected],
                                "no_ppr_top5": prior_top_ids, "ppr_top5": previous_ppr_ids,
                                "promoted_chunks_and_visible_edges": promoted_details,
                                "candidate_pool_limit": "Only saved top-5 results are available; full dense/RRF candidate pool was not preserved.",
                            })
                    elif prior:
                        row["prior_hybrid_labels_match_current"] = False

                if with_gemini_embeddings and eligible:
                    query_embedding = query_embeddings[case["query"]]
                    diagnostics = {}
                    dense_hybrid = retriever_module.retrieve(
                        case["query"], db, business_id=business_id,
                        top_k=TOP_K, query_embedding=query_embedding,
                        hard_filters=filters,
                        diagnostics=diagnostics,
                        retrieval_mode="hybrid",
                        enable_ppr=True,
                    )
                    dense_hybrid_ids = [int(item.chunk_id) for item in dense_hybrid]
                    row["gemini_bm25_rrf_ppr_top_chunk_ids"] = dense_hybrid_ids
                    row["retrieval_mode"] = diagnostics.get("retrieval_mode")
                    row["retrieval_fallback_stage"] = diagnostics.get("retrieval_fallback_stage")
                    dense_retrieval_modes[str(diagnostics.get("retrieval_mode") or "unknown")] += 1
                    if diagnostics.get("retrieval_fallback_stage"):
                        dense_fallback_stages[str(diagnostics["retrieval_fallback_stage"])] += 1

                    original_lexical = retriever_module._retrieve_lexical
                    try:
                        dense_no_ppr = retriever_module.retrieve(
                            case["query"], db, business_id=business_id,
                            top_k=TOP_K, query_embedding=query_embedding, hard_filters=filters,
                            retrieval_mode="hybrid",
                            enable_ppr=False,
                        )
                        dense_no_ppr_ids = [int(item.chunk_id) for item in dense_no_ppr]
                        row["gemini_bm25_rrf_no_ppr_top_chunk_ids"] = dense_no_ppr_ids

                        # Offline replay of the production auto router using
                        # this exact case's lexical candidates and filter set.
                        auto_mode, auto_reason = _select_retrieval_mode(
                            "auto",
                            filters or {},
                            retriever_module._query_sku_identifiers(case["query"], filters),
                            lexical,
                        )
                        auto_ids = base_top if auto_mode == "bm25" else dense_no_ppr_ids
                        row["auto_routed_mode"] = auto_mode
                        row["auto_routing_reason"] = auto_reason
                        row["auto_top_chunk_ids"] = auto_ids
                        filter_result_ids["auto_no_ppr_top5"] = auto_ids
                        auto_route_counts[auto_reason] += 1
                        row["auto_no_ppr"] = rank_metrics(expected, auto_ids)
                        by_method["auto_no_ppr"].append(row["auto_no_ppr"])
                        by_shop_type[str(business_id)][case["case_type"]]["auto_no_ppr"].append(row["auto_no_ppr"])
                        by_shop_type[f"type:{case['case_type']}"][str(business_id)]["auto_no_ppr"].append(row["auto_no_ppr"])

                        retriever_module._retrieve_lexical = lambda *args, **kwargs: []
                        dense_vector = retriever_module.retrieve(
                            case["query"], db, business_id=business_id,
                            top_k=TOP_K, query_embedding=query_embedding, hard_filters=filters,
                            retrieval_mode="hybrid",
                            enable_ppr=False,
                        )
                        dense_vector_ids = [int(item.chunk_id) for item in dense_vector]
                        row["gemini_vector_only_top_chunk_ids"] = dense_vector_ids
                    finally:
                        retriever_module._retrieve_lexical = original_lexical
                    filter_result_ids.update({
                        "gemini_hybrid_ppr_top5": dense_hybrid_ids,
                        "gemini_hybrid_no_ppr_top5": dense_no_ppr_ids,
                        "gemini_vector_top5": dense_vector_ids,
                    })

                    if eligible:
                        for method, ids, output_key in (
                            ("gemini_bm25_rrf_ppr", dense_hybrid_ids, "gemini_bm25_rrf_ppr"),
                            ("gemini_bm25_rrf_no_ppr", dense_no_ppr_ids, "gemini_bm25_rrf_no_ppr"),
                            ("gemini_vector_only", dense_vector_ids, "gemini_vector_only"),
                        ):
                            row[output_key] = rank_metrics(expected, ids)
                            by_method[method].append(row[output_key])
                            by_shop_type[str(business_id)][case["case_type"]][method].append(row[output_key])
                            by_shop_type[f"type:{case['case_type']}"][str(business_id)][method].append(row[output_key])
                        if row["gemini_bm25_rrf_ppr"]["ndcg_at_5"] < row["gemini_bm25_rrf_no_ppr"]["ndcg_at_5"]:
                            ppr_ids = dense_hybrid_ids[:TOP_K]
                            no_ppr_ids = dense_no_ppr_ids[:TOP_K]
                            ppr_ranks = {chunk_id: rank for rank, chunk_id in enumerate(ppr_ids, start=1)}
                            no_ppr_ranks = {chunk_id: rank for rank, chunk_id in enumerate(no_ppr_ids, start=1)}
                            visible_items = {int(item.chunk_id): item for item in [*dense_no_ppr, *dense_hybrid]}
                            promoted = []
                            for promoted_id in ppr_ids:
                                if promoted_id in no_ppr_ranks:
                                    continue
                                item = visible_items.get(promoted_id)
                                peers = []
                                if item:
                                    for peer_id in no_ppr_ids:
                                        peer = visible_items.get(peer_id)
                                        if peer:
                                            reasons = edge_reasons(item, peer)
                                            if reasons:
                                                peers.append({"peer_chunk_id": peer_id, "reasons": reasons})
                                promoted.append({
                                    "chunk_id": promoted_id,
                                    "ppr_rank": ppr_ranks[promoted_id],
                                    "edges_to_no_ppr_top5": peers,
                                })
                            ppr_diagnostics.append({
                                "diagnostic_kind": "fresh_dense_hybrid_ppr_degradation",
                                "case_id": case["case_id"], "business_id": business_id,
                                "industry": case["industry"], "case_type": case["case_type"],
                                "query_family": case.get("query_family", case["case_id"]),
                                "query": case["query"],
                                "expected_chunk_ids": sorted(expected),
                                "expected_ranks_no_ppr_top5": [
                                    {"chunk_id": value, "rank": no_ppr_ranks.get(value)} for value in expected
                                ],
                                "expected_ranks_ppr_top5": [
                                    {"chunk_id": value, "rank": ppr_ranks.get(value)} for value in expected
                                ],
                                "no_ppr_top5": no_ppr_ids,
                                "ppr_top5": ppr_ids,
                                "promoted_chunks_and_visible_edges": promoted,
                            })
                if filters:
                    method_leaks = {}
                    for method, result_ids in filter_result_ids.items():
                        violations = []
                        for chunk_id in result_ids:
                            entries = chunk_entries.get(chunk_id, [])
                            if not _audit_chunk_matches_generated_filter(
                                entries, case["case_type"], filters,
                            ):
                                violations.append(chunk_id)
                        method_leaks[method] = violations
                        stats = hard_filter_leakage_by_method[method]
                        stats["filtered_case_count"] += 1
                        stats["returned_chunk_count"] += len(result_ids)
                        stats["leakage_chunk_count"] += len(violations)
                        if method == "bm25_candidates":
                            hard_filter_violations.add(case["case_type"], len(violations))
                            hard_filter_audit[case["case_type"]]["leakage_chunk_count"] += len(violations)
                    row["hard_filter_leakage_chunk_ids_by_method"] = method_leaks
                results.append(row)
                source_rows.append({
                    "case_id": case["case_id"], "business_id": business_id,
                    "industry": case["industry"], "industry_source": case["industry_source"],
                    "query_family": case.get("query_family", case["case_id"]),
                    "case_type": case["case_type"], "query": case["query"],
                    "expected_chunk_ids": ",".join(map(str, case.get("expected_chunk_ids", []))),
                    "hard_filters": json.dumps(filters, ensure_ascii=False) if filters else "",
                    "source_document": case.get("source_evidence", ""),
                    "label_status": case["label_status"],
                    "expected_behavior": case.get("expected_behavior", ""),
                    "retrieved_bm25_top5": ",".join(map(str, base_top)),
                    "source_chunk_text": case.get("source_chunk_text", ""),
                })

    product_audits = source_audits
    for case in cases:
        if case["case_type"] == "product_info" and not case.get("metric_eligible"):
            label_failures.append(case["case_id"])

    prior_hybrid = [row for row in results if row.get("prior_hybrid_labels_match_current")]
    methods = {name: aggregate(rows) for name, rows in by_method.items()}
    if prior_hybrid:
        for key in ("prior_gemini_hybrid_no_ppr", "prior_gemini_hybrid_ppr", "prior_gemini_hybrid_exact_entity_ppr_85_15"):
            valid = [row[key] for row in prior_hybrid if isinstance(row.get(key), dict)]
            if not valid:
                continue
            methods[key] = {
                "case_count": len(valid),
                **{metric: round(sum(value[metric] for value in valid) / len(valid), 6) for metric in ("recall_at_5", "mrr", "ndcg_at_5")},
                "run_status": (
                    "fresh_offline_rerank_of_saved_hybrid_no_ppr_top5_only;_candidate_pool_limited"
                    if key == "prior_gemini_hybrid_exact_entity_ppr_85_15"
                    else "reused_prior_per_case_results_same_query_and_gold_labels;_not_rerun_dense_path"
                ),
            }

    by_group = {}
    for key, methods_for_group in by_shop_type.items():
        by_group[key] = {
            group: {name: aggregate(rows) for name, rows in method_rows.items()}
            for group, method_rows in methods_for_group.items()
        }

    dense_ppr_regressed = bool(
        methods.get("gemini_bm25_rrf_ppr")
        and methods.get("gemini_bm25_rrf_no_ppr")
        and methods["gemini_bm25_rrf_ppr"]["ndcg_at_5"] < methods["gemini_bm25_rrf_no_ppr"]["ndcg_at_5"]
    )
    quality_gate_reasons = [
        "Human answer support/correctness review is still pending.",
        "No positive service/rental ground-truth dataset is available.",
        "Live stock/status correctness and final answer quality were not evaluated.",
    ]
    if not with_gemini_embeddings:
        quality_gate_reasons.append("Fresh dense hybrid evaluation was not run.")
    if dense_ppr_regressed:
        quality_gate_reasons.append("Current PPR reduced NDCG@5 versus the same-run hybrid without PPR.")

    label_audit_path = output_dir / "industry-rag-validated-source-review.csv"
    with label_audit_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(product_audits[0]) if product_audits else [])
        if product_audits:
            writer.writeheader()
            writer.writerows(product_audits)
    expanded_path = output_dir / "industry-rag-expanded-human-review.csv"
    with expanded_path.open("w", encoding="utf-8-sig", newline="") as stream:
        fields = list(source_rows[0]) if source_rows else []
        writer = csv.DictWriter(stream, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(source_rows)
    results_path = output_dir / "industry-rag-expanded-results.jsonl"
    results_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results), encoding="utf-8")
    cases_path = output_dir / "industry-rag-expanded-evaluation-set.jsonl"
    cases_path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8")
    result_path = output_dir / "industry-rag-ppr-diagnostics.jsonl"
    result_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ppr_diagnostics), encoding="utf-8")
    metrics = {
        "status": "completed" if not label_failures else "blocked_label_failures",
        "local_only": True,
        "embedding_api_calls": embedding_api_calls,
        "embedding_query_count": embedding_query_count,
        "embedding_cache_hit": embedding_cache_hit,
        "embedding_cache_hits": embedding_cache_hits if with_gemini_embeddings else 0,
        "embedding_cache_misses": embedding_cache_misses if with_gemini_embeddings else 0,
        "embedding_provider": settings.EMBEDDING_PROVIDER if with_gemini_embeddings else None,
        "embedding_model": settings.EMBEDDING_MODEL if with_gemini_embeddings else None,
        "embedding_dimension": settings.EMBEDDING_DIMENSION if with_gemini_embeddings else None,
        "dense_hybrid_rerun": with_gemini_embeddings,
        "dense_hybrid_rerun_reason": None if with_gemini_embeddings else "Gemini embedding evaluation was not requested; historical dense metrics are only a same-label reference.",
        "dense_retrieval_modes": dict(dense_retrieval_modes),
        "dense_fallback_stages": dict(dense_fallback_stages),
        "tenant_count": len(shops),
        "shop_industry_inference": list(shops.values()),
        "industry_inference_is_not_persisted_business_setting": True,
        "product_source_audit": {
            "mapped_product_cases": len(product_audits),
            "textually_supported": sum(row["source_topically_supports_product_identity"] for row in product_audits),
            "failed": len(label_failures),
            "scope": "Product name or exact SKU exists in a tenant-owned ready mapped chunk; verifies topical product support, not correctness of live price/stock or all answer claims.",
            "human_answer_review_status": "still_pending",
        },
        "expanded_case_counts": dict(sorted(CounterLike.counts_for(cases).items())),
        "duplicate_case_rows_removed": duplicate_case_rows_removed,
        "methods": methods,
        "paired_uncertainty": {
            "bm25_mmr_ndcg_at_5_delta_vs_bm25": paired_cluster_bootstrap_delta(
                results,
                baseline_key="bm25",
                candidate_key="bm25_mmr",
                metric="ndcg_at_5",
            ),
        },
        "mmr_ablation": {
            "enabled_in_serving": False,
            "diversity_weight": MMR_DIVERSITY_WEIGHT,
            "candidate_window": max(TOP_K, TOP_K * MMR_CANDIDATE_MULTIPLIER),
            "candidate_pool_per_case_saved": True,
            "max_per_document_by_topic": {"products": 4, "other": 2},
            "overlap_metric": "Jaccard over normalized lexical tokens",
        },
        "auto_routing_ablation": {
            "status": "same_run_offline_replay" if with_gemini_embeddings else "not_run",
            "routes": dict(auto_route_counts),
            "method": methods.get("auto_no_ppr"),
            "router": "Production _select_retrieval_mode('auto') replayed on the same BM25 candidates; exact hard-filter/SKU queries stay lexical; weak lexical queries select same-run hybrid RRF without PPR.",
            "latency_or_provider_cost_measured": False,
        },
        "by_shop_and_case_type": by_group,
        "abstention_probes": dict(abstention),
        "hard_filter_violation_counts": hard_filter_violations.counts,
        "hard_filter_violation_counts_scope": "Independent audit oracle on BM25 candidate lists; all returned/reranked methods are summarized separately in hard_filter_leakage_by_method.",
        "hard_filter_leakage_by_method": dict(hard_filter_leakage_by_method),
        "hard_filter_audit": dict(hard_filter_audit),
        "ppr_diagnosis": {
            "current_graph_edges": {"same_product_or_sku": 3.0, "same_document_parent": 2.0, "adjacent_chunk": 0.35},
            "current_lexical_ppr_degraded_product_query_cases": sum(
                bool(row.get("expected_chunk_ids_dropped_from_top5"))
                for row in ppr_diagnostics
                if row.get("diagnostic_kind") == "fresh_lexical_ppr_diagnostic"
            ),
            "exact_entity_variant": "Offline only: cloned candidates keep only catalog product_id/SKU, remove parent_id/chunk_index, and blend 85% BM25 order + 15% exact-edge PPR order.",
            "edge_case_details": len(ppr_diagnostics),
            "historical_hybrid_degraded_cases": sum(row.get("diagnostic_kind") == "historical_dense_hybrid_ppr_degradation" for row in ppr_diagnostics),
            "historical_hybrid_limited_rerank": "Historical ablation only: reranked each saved no-PPR hybrid top-5 set, so it could not add candidates. A separate fresh dense path was rerun when dense_hybrid_rerun is true.",
            "fresh_dense_hybrid_ppr_degraded_cases": sum(row.get("diagnostic_kind") == "fresh_dense_hybrid_ppr_degradation" for row in ppr_diagnostics),
            "no_serving_configuration_changed": True,
        },
        "case_totals": {
            "total_cases": len(cases),
            "retrieval_metric_eligible": sum(bool(case.get("metric_eligible") and case.get("expected_chunk_ids")) for case in cases),
            "non_retrieval_or_abstention_probes": sum(not bool(case.get("metric_eligible") and case.get("expected_chunk_ids")) for case in cases),
            "metric_eligible_query_families": len({
                case.get("query_family", case["case_id"])
                for case in cases if case.get("metric_eligible") and case.get("expected_chunk_ids")
            }),
        },
        "dense_hybrid_case_scope": "Fresh dense/hybrid methods run only for metric-eligible source-labelled cases; abstention and empty-coverage probes were checked with lexical BM25 only.",
        "quality_gate": {
            "status": "blocked" if quality_gate_reasons else "passed",
            "reasons": quality_gate_reasons,
            "current_ppr_ndcg_regressed_vs_same_run_no_ppr": dense_ppr_regressed,
            "configuration_changed": False,
        },
        "limits": [
            "Shop industry is inferred for evaluation from local documents/catalog and is not written to tenant settings.",
            "Shops without identifiable catalog/doc evidence remain unclassified; no synthetic positive labels were created for them.",
            "BM25 and two lexical PPR variants were freshly rerun against local PostgreSQL; dense hybrid metrics are fresh only when dense_hybrid_rerun is true.",
            "RAG chunk ranking is not the same as final product recommendation display; current stock/status safety is not evaluated at answer/display level here.",
            "Policy cases have source phrase matches but still require a domain reviewer for answer-level correctness.",
        ],
        "artifacts": {
            "source_review_csv": label_audit_path.name,
            "expanded_review_csv": expanded_path.name,
            "expanded_results_jsonl": results_path.name,
            "expanded_cases_jsonl": cases_path.name,
            "ppr_diagnostics_jsonl": result_path.name,
        },
    }
    metrics_path = output_dir / "industry-rag-ppr-expansion-report.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metrics


class CounterLike:
    def __init__(self):
        self.counts = defaultdict(int)

    def add(self, key: str, amount: int):
        self.counts[key] += int(amount)

    @staticmethod
    def counts_for(cases: list[dict]) -> dict[str, int]:
        counts = defaultdict(int)
        for case in cases:
            counts[case["case_type"]] += 1
        return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--prior-cases", type=Path)
    parser.add_argument("--with-gemini-embeddings", action="store_true")
    parser.add_argument(
        "--require-embedding-cache",
        action="store_true",
        help="Fail if any query embedding is missing from the output directory cache; do not call Gemini.",
    )
    args = parser.parse_args()
    print(json.dumps(evaluate(
        args.output_dir, args.prior_cases,
        with_gemini_embeddings=args.with_gemini_embeddings,
        require_embedding_cache=args.require_embedding_cache,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
