"""Re-evaluate answers against saved vector passages; privacy actions use SQLite fixtures."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import unicodedata
import re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" if (ROOT / "backend").is_dir() else ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import app.models
from app.models.audit_log import AuditLog
from app.models.customer import Customer
from app.rag.answer_guard import has_valid_citations
from app.rag.llm_caller import call_llm
from app.rag.prompt_builder import build_prompt, localize_rag_fallback, NO_CONTEXT_CHAT_FALLBACK, SERVICE_ERROR_CHAT_FALLBACK
from app.rag.retriever import RetrievedChunk
from app.services.privacy_service import customer_memory_opt_out_reply


def _normalized_evidence(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[‐‑‒–—−]", "-", value)
    return re.sub(r"\s+", " ", value).strip()


def _evidence_checks(case: dict, answer: str) -> tuple[list[str], list[str]]:
    normalized = _normalized_evidence(answer)
    missing = [term for term in case.get("must_include", [])
               if _normalized_evidence(term) not in normalized]
    forbidden = [term for term in case.get("must_not_include", [])
                 if _normalized_evidence(term) in normalized]
    return missing, forbidden


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=Path, help="Original JSONL contracts, including forbidden terms missing from legacy reports.")
    parser.add_argument("--case-id", action="append", default=[], help="Regenerate selected cases; revalidate the other saved answers.")
    parser.add_argument("--provider-interval", type=float, default=0,
                        help="Minimum seconds between regenerated answers; reused answers do not call the provider.")
    args = parser.parse_args()
    if args.provider_interval < 0:
        parser.error("Provider interval must be nonnegative.")
    previous = json.loads(args.report.read_text(encoding="utf-8"))
    if args.cases:
        contracts = {row["id"]: row for row in (
            json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()
        )}
        for case in previous["cases"]:
            if case["id"] not in contracts:
                parser.error("Case has no original contract: " + case["id"])
            contract = contracts[case["id"]]
            case.update(must_include=contract.get("must_include", []),
                        must_not_include=contract.get("must_not_include", []))
    if previous.get("retrieval", {}).get("fully_hybrid_cases") != len(previous["cases"]):
        parser.error("Input must contain a complete vector run, without retrieval fallback.")
    unknown = set(args.case_id) - {case["id"] for case in previous["cases"]}
    if unknown:
        parser.error("Unknown case IDs: " + ", ".join(sorted(unknown)))
    engine = create_engine("sqlite://")
    Customer.__table__.create(engine)
    AuditLog.__table__.create(engine)
    results, errors = [], Counter()
    citations = citation_cases = generated = crm_actions = 0
    required_found = required_total = forbidden_found = 0
    last_provider_started = None
    with Session(engine) as db:
        db.add(Customer(id=1, business_id=1, channel="telegram", external_user_id="synthetic-evaluation"))
        db.commit()
        for index, case in enumerate(previous["cases"], 1):
            started = time.perf_counter()
            answer, error_type, valid = "", None, None
            method, status = "cached_vector_context", "service_error"
            privacy = customer_memory_opt_out_reply(db, 1, 1, case["query"])
            if privacy is not None:
                answer, method = privacy, "isolated_crm_privacy_action"
                verified = bool(db.get(Customer, 1).fact_extraction_opt_out)
                crm_actions += int(verified)
                generated += int(bool(answer.strip()))
                status = "answered" if verified else "handoff_required"
            else:
                citation_cases += 1
                metadata = case.get("retrieved_metadata") or [{} for _ in case["retrieved_contents"]]
                chunks = [RetrievedChunk(int(chunk_id), i + 1, content, 1.0, {**(meta or {}), "source": filename}, filename=filename)
                          for i, (chunk_id, content, filename, meta) in enumerate(zip(
                              case["retrieved_chunk_ids"], case["retrieved_contents"], case["retrieved_sources"], metadata))]
                try:
                    if not args.case_id or case["id"] in args.case_id:
                        if last_provider_started is not None and args.provider_interval:
                            time.sleep(max(0, args.provider_interval - (time.monotonic() - last_provider_started)))
                        last_provider_started = time.monotonic()
                        answer = call_llm(build_prompt(case["query"], chunks))
                    else:
                        answer = case.get("answer", "")
                    if not answer or not answer.strip():
                        raise RuntimeError("empty_llm_answer")
                    generated += 1
                    valid = has_valid_citations(answer, case["retrieved_contents"], query=case["query"])
                    citations += int(valid)
                    status = "answered" if valid else "handoff_required"
                except Exception as error:
                    error_type = type(error).__name__
                    errors[error_type] += 1
                    answer = ""
            fallback = NO_CONTEXT_CHAT_FALLBACK if status == "handoff_required" else SERVICE_ERROR_CHAT_FALLBACK
            served_answer = answer if status == "answered" else localize_rag_fallback(fallback, query=case["query"])
            missing, forbidden = _evidence_checks(case, served_answer)
            required_total += len(case.get("must_include", []))
            required_found += len(case.get("must_include", [])) - len(missing)
            forbidden_found += len(forbidden)
            results.append({**case, "answer": answer,
                            "served_answer": served_answer,
                            "answer_status": status, "answer_method": method, "valid_citation_gate": valid,
                            "must_include_missing": missing, "must_not_include_found": forbidden,
                            "literal_evidence_passed": not missing and not forbidden,
                            "citation_required": method != "isolated_crm_privacy_action",
                            "answer_origin": "crm_fixture" if privacy is not None else "regenerated" if not args.case_id or case["id"] in args.case_id else "reused",
                            "answer_error_type": error_type, "answer_latency_ms": round((time.perf_counter() - started) * 1000, 2)})
            print(f"{index}/{len(previous['cases'])} {case['id']}: {status}", flush=True)
    engine.dispose()
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "mode": "cached_vector_answers_with_isolated_crm_privacy_fixture",
              "data_scope": "synthetic passages and an in-memory customer; no external channel sends",
              "regenerated_case_ids": args.case_id or [case["id"] for case in previous["cases"]],
              "retrieval": {**previous["retrieval"], "reused_from": args.report.name, "recomputed": False},
              "answers": {"attempted": len(results), "generated_nonempty": generated,
                          "citation_cases": citation_cases, "citation_passed": citations,
                          "citation_gate_pass_rate": round(citations / max(1, citation_cases), 4),
                          "must_include_term_rate": round(required_found / max(1, required_total), 4),
                          "must_include_terms_checked": required_total,
                          "must_not_include_violations": forbidden_found,
                          "literal_evidence_passed_cases": sum(c["literal_evidence_passed"] for c in results),
                          "verified_crm_actions": crm_actions,
                          "answered_cases": sum(c["answer_status"] == "answered" for c in results),
                          "handoff_cases": sum(c["answer_status"] == "handoff_required" for c in results),
                          "provider_or_empty_errors_by_type": dict(errors)},
              "limitations": ["Retrieval is reused, not recomputed. Passing citation validation does not prove every semantic claim.",
                              "Literal evidence checks are diagnostic only; paraphrases can be correct without literal matches.",
                              "Privacy actions use a synthetic customer. Live product price/stock routing needs separate CRM tests."],
              "cases": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["answers"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
