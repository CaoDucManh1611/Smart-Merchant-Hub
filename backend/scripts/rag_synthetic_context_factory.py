"""Ephemeral, synthetic-only SQLite contexts for real graph evaluation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.bases import TenantBase
from app.models import BusinessSetting, Conversation, Customer, Document, DocumentChunk, Message, Product
from app.rag.run_logger import query_metadata
from scripts.evaluate_rag_answer_generation import EvaluationContext


_BUSINESS_ID_BASE = 910_000
_CAPABILITIES = [
    "CORE_CRM",
    "RETAIL_TOOLS",
    "INVENTORY_TOOLS",
    "RECOMMENDATION_TOOLS",
]
_SETTING_KEY = "workspace_modules"


def synthetic_context(case: dict) -> EvaluationContext:
    """Create a fresh in-memory tenant DB, seed only this case, and return it."""
    case_index = case_index_safe(case)
    if case_index <= 0:
        raise ValueError("synthetic_case_id_missing_sequence")
    business_id = _BUSINESS_ID_BASE + case_index
    # The PostgreSQL test harness wraps SQLAlchemy's factory so legacy
    # sqlite:// fixtures run on isolated PostgreSQL schemas. This evaluator
    # is deliberately different: its synthetic tenant DB must remain a real,
    # private in-memory SQLite database for read-only PRAGMA enforcement.
    engine_factory = getattr(create_engine, "_smh_original_create_engine", create_engine)
    engine = engine_factory(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TenantBase.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    _seed_workspace(db, business_id)
    customer = Customer(
        id=1,
        business_id=business_id,
        channel="telegram",
        external_user_id=f"synthetic-customer-{case_index}",
        name="Synthetic Customer",
        custom_fields={},
        fact_extraction_opt_out=True,
        status="active",
    )
    db.add(customer)
    conversation = Conversation(
        id=1,
        business_id=business_id,
        customer_id=1,
        channel="telegram",
        status="open",
        bot_mode="auto",
        priority="normal",
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(conversation)
    db.flush()

    _seed_catalog(db, case, business_id)
    _seed_knowledge(db, case, business_id)
    _seed_history(db, case, conversation.id)
    db.commit()

    # The evaluator will enforce PRAGMA query_only before graph execution.
    return EvaluationContext(
        db=db,
        business_id=business_id,
        conversation=conversation,
        synthetic=True,
        read_only=True,
        platform_db=None,
        industry_config=None,
    )


def _seed_workspace(db: Session, business_id: int) -> None:
    config = {
        "config_schema_version": 2,
        "business_model": "RETAIL",
        "business_type": "retail",
        "industry_ids": [],
        "enabled_modules": ["retail"],
        "enabled_capabilities": _CAPABILITIES,
        "capability_source": "explicit",
        "config_version": 1,
        "recommendation_industry": "general_retail",
        "purchase_model_reference_industry": "general_retail",
    }
    db.add(BusinessSetting(
        business_id=business_id,
        key=_SETTING_KEY,
        value=json.dumps(config, separators=(",", ":")),
    ))


def _seed_catalog(db: Session, case: dict, business_id: int) -> None:
    counter = 0
    for evidence_id, evidence in (case.get("evidence") or {}).items():
        if not evidence_id.startswith("catalog:") or not isinstance(evidence, dict):
            continue
        owner_id = business_id + 1 if "tenant-b" in evidence_id else business_id
        items: list[dict] = []
        if isinstance(evidence.get("products"), list):
            for item in evidence["products"]:
                items.append(item if isinstance(item, dict) else {"name": str(item)})
        elif isinstance(evidence.get("skus"), list):
            items.extend({"name": str(sku), "sku": str(sku)} for sku in evidence["skus"])
        elif any(key in evidence for key in ("name", "price_vnd", "price", "available_stock", "stock")):
            name = evidence.get("name")
            if not name:
                name = evidence_id.partition(":")[2].replace("-", " ").title()
            items.append({**evidence, "name": name})

        for item in items:
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                continue
            counter += 1
            name = str(item["name"]).strip()
            sku = str(item.get("sku") or f"SYNTH-{case_index_safe(case)}-{counter}")[:80]
            price = item.get("price_vnd", item.get("price"))
            stock = item.get("available_stock", item.get("stock_quantity", item.get("stock")))
            if stock is None and item.get("status") == "out_of_stock":
                stock = 0
            descriptive = []
            for key in ("description", "aliases", "size", "compatibility", "specifications", "sku"):
                value = item.get(key)
                if value not in (None, "", [], {}):
                    descriptive.append(f"{key}: {value}")
            metadata = {
                key: item[key]
                for key in ("aliases", "size", "compatibility", "specifications", "variant")
                if item.get(key) not in (None, "", [], {})
            }
            db.add(Product(
                business_id=owner_id,
                sku=sku,
                name=name,
                description="; ".join(map(str, descriptive)) or None,
                price=Decimal(str(price or 0)),
                stock_quantity=int(stock or 0),
                reserved_quantity=0,
                status="active",
                metadata_=metadata,
            ))


def _seed_knowledge(db: Session, case: dict, business_id: int) -> None:
    chunks: list[tuple[str, str]] = []
    for evidence_id, evidence in (case.get("evidence") or {}).items():
        if not isinstance(evidence, dict):
            continue
        if evidence_id.startswith(("policy:", "kb:")) and evidence.get("text"):
            chunks.append((evidence_id, str(evidence["text"])))
        elif evidence_id.startswith("image-observation:"):
            ocr = str(evidence.get("ocr_text") or "")
            confidence = evidence.get("confidence")
            chunks.append((evidence_id, f"Synthetic customer image observation: ảnh có dòng chữ {ocr}; confidence {confidence}. Đây là quan sát hình ảnh, không xác nhận giá, tồn kho hoặc SKU."))
        elif evidence_id.startswith("calendar:"):
            # The synthetic fixture's reference date is fixed by the checked-in dataset.
            chunks.append((evidence_id, "Lịch tư vấn ngày 06/11/2026: khung 10:00 đang trống theo lịch synthetic-calendar-v1; dịch vụ dự kiến 30 phút. Chỉ là dữ liệu tra cứu, chưa tạo lịch hẹn."))

    for index, (evidence_id, content) in enumerate(chunks):
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        document = Document(
            business_id=business_id,
            filename=f"synthetic-{index + 1}.txt",
            file_type="txt",
            file_size=len(content.encode("utf-8")),
            status="ready",
            chunk_count=1,
            content_hash=content_hash,
            embedding_status="lexical_only",
        )
        db.add(document)
        db.flush()
        db.add(DocumentChunk(
            document_id=document.id,
            content=content,
            chunk_index=0,
            embedding=None,
            metadata_={"synthetic_evidence_id": evidence_id, "synthetic": True},
        ))


def _seed_history(db: Session, case: dict, conversation_id: int) -> None:
    turns = case.get("conversation") or []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for index, turn in enumerate(turns[:-1]):
        role = turn["role"]
        db.add(Message(
            conversation_id=conversation_id,
            channel="telegram",
            sender_type="customer" if role == "user" else "bot",
            direction="inbound" if role == "user" else "outbound",
            content=turn["content"],
            status="received" if role == "user" else "sent",
            received_at=now - timedelta(seconds=(len(turns) - index) * 5),
        ))


def case_index_safe(case: dict) -> int:
    match = re.search(r"(?:answer-)?(\d+)", str(case.get("case_id", "")))
    return int(match.group(1)) if match else 0


def synthetic_query(case: dict) -> str:
    """Reproduce the safe image-observation input created before graph routing."""
    query = next(turn["content"] for turn in reversed(case["conversation"]) if turn["role"] == "user")
    for evidence_id, evidence in (case.get("evidence") or {}).items():
        if evidence_id.startswith("image-observation:") and isinstance(evidence, dict):
            query += f"\nVISIBLE_IMAGE_OBSERVATION: {evidence.get('ocr_text', '')} (confidence {evidence.get('confidence', 'unknown')})"
    return query
