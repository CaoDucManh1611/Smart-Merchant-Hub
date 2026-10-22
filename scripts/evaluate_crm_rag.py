"""Evaluate structured CRM chat routing and evidence on synthetic SQLite data."""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.database.bases import TenantBase  # noqa: E402
from app.database.session import Base  # noqa: E402
from app.models.business import Business, User  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.customer_note import CustomerNote  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.models.message import Message  # noqa: E402
from app.models.lead import Lead  # noqa: E402
from app.models.crm_workspace_config import CrmWorkspaceConfig  # noqa: E402
from app.models.permission import PermissionOverride  # noqa: E402
from app.rag.evaluation import evaluate_predictions  # noqa: E402
from app.schemas.rag import ChatRequest  # noqa: E402
from app.services.crm_knowledge import answer_from_crm  # noqa: E402


CASE_PATH = ROOT / "docs" / "crm-rag-evaluation-set.jsonl"
REPORT_PATH = ROOT / "docs" / "crm-rag-evaluation-report.json"
TENANT_ID = 42
CITATION = re.compile(r"\[(?:Nguồn|Source)\s+(\d+)\]", re.IGNORECASE)


def crm_citation_valid(answer: str, sources: list) -> bool:
    """Check that each explicit marker resolves to a returned CRM record/source."""
    citation_ids = [int(value) for value in CITATION.findall(answer or "")]
    return bool(citation_ids) and all(
        1 <= citation_id <= len(sources)
        and bool(sources[citation_id - 1].record_id or sources[citation_id - 1].source_type == "crm_lead_query")
        for citation_id in citation_ids
    )


def load_cases() -> list[dict]:
    return [json.loads(line) for line in CASE_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def prepare_fixture() -> tuple[object, Session, User, User]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Business.__table__, User.__table__])
    TenantBase.metadata.create_all(engine, tables=[
        Customer.__table__, Conversation.__table__, Message.__table__, Lead.__table__,
        CustomerNote.__table__, CrmWorkspaceConfig.__table__, PermissionOverride.__table__,
    ])
    db = Session(engine)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    db.add_all([
        Business(id=TENANT_ID, name="Synthetic CRM Eval", slug="synthetic-crm-eval"),
        Business(id=43, name="Other Tenant", slug="synthetic-other-tenant"),
    ])
    db.flush()
    owner = User(
        id=1, business_id=TENANT_ID, full_name="Người phụ trách", email="owner@example.invalid",
        password_hash="fixture", role="admin", is_active=True,
    )
    limited = User(
        id=2, business_id=TENANT_ID, full_name="Tài khoản giới hạn", email="limited@example.invalid",
        password_hash="fixture", role="crm_limited", is_active=True,
    )
    db.add_all([owner, limited])
    db.flush()

    customer = Customer(id=101, business_id=TENANT_ID, channel="web", external_user_id="fixture-101",
                        name="Nguyễn Văn An", status="active")
    deal_customer = Customer(id=102, business_id=TENANT_ID, channel="web", external_user_id="fixture-102",
                             name="Trần Bình", status="active")
    similar_customer = Customer(id=103, business_id=TENANT_ID, channel="web", external_user_id="fixture-103",
                                name="Nguyễn Văn Anh", status="active")
    other_tenant_customer = Customer(id=901, business_id=43, channel="web", external_user_id="fixture-901",
                                     name="Ngoài phạm vi tenant", status="active")
    conversation = Conversation(id=401, business_id=TENANT_ID, customer_id=101, channel="web",
                                status="open", created_at=now, updated_at=now)
    db.add_all([customer, deal_customer, similar_customer, other_tenant_customer, conversation])
    db.flush()

    db.add_all([
        Message(id=501, conversation_id=401, channel="web", direction="inbound", sender_type="customer",
                content="Khách muốn khảo sát website và nhận báo giá trong tuần này.", received_at=now),
        CustomerNote(id=601, business_id=TENANT_ID, customer_id=101,
                     content="Cần báo giá trước thứ Sáu.", created_by=1, created_at=now, updated_at=now),
        Lead(id=201, business_id=TENANT_ID, customer_id=101, title="Gia hạn hợp đồng", stage="proposal",
             status="open", assigned_user_id=1, created_at=this_month, updated_at=now),
        Lead(id=202, business_id=TENANT_ID, customer_id=102, title="Thiết kế website", stage="qualified",
             status="open", assigned_user_id=2, created_at=this_month, updated_at=now),
        Lead(id=203, business_id=TENANT_ID, customer_id=102, title="Gói bảo trì cũ", stage="proposal",
             status="closed", assigned_user_id=1, created_at=this_month - timedelta(days=1), updated_at=now),
        Lead(id=901, business_id=43, customer_id=901, title="Tenant khác", stage="proposal",
             status="open", assigned_user_id=1, created_at=this_month, updated_at=now),
    ])
    db.commit()
    return engine, db, owner, limited


def main() -> int:
    cases = load_cases()
    engine, db, owner, limited = prepare_fixture()
    predictions = []
    for case in cases:
        user = limited if case.get("user_variant") == "no_crm_access" else owner
        started = time.perf_counter()
        response = answer_from_crm(
            db,
            TENANT_ID,
            ChatRequest(query=case["query"]),
            user=user,
            permission_db=db,
            user_db=db,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        sources = list(response.sources)
        source_contents = [source.content for source in sources]
        predictions.append({
            "id": case["id"],
            "action": response.action,
            "answer": response.answer,
            "retrieved_contents": source_contents,
            "retrieved_sources": [source.source_type for source in sources if source.source_type],
            "citation_valid": crm_citation_valid(response.answer, sources),
            "handoff_required": response.handoff_required,
            "latency_ms": latency_ms,
            # Structured SQL answers make no model call; online logs use the
            # same zero-cost convention for this retrieval mode.
            "estimated_ai_cost": 0.0,
            "answer_status": response.answer_status,
            "source_record_ids": [source.record_id for source in sources],
        })

    metrics = evaluate_predictions(cases, predictions)
    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": CASE_PATH.name,
        "mode": "synthetic SQLite; no customer data, LLM, embeddings, or external API",
        "metrics": metrics,
        "predictions": predictions,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    db.close()
    engine.dispose()
    print(json.dumps({"report": str(REPORT_PATH), "metrics": metrics}, ensure_ascii=False, indent=2))
    return 0 if metrics.get("missing_prediction_count") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
