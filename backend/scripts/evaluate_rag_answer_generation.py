"""Run synthetic answer-quality cases through the application's graph_reply path.

Provider calls are disabled unless the operator explicitly supplies the opt-in
flag. Evaluation contexts must be synthetic, read-only, in-memory SQLite.
Correctness and groundedness are intentionally left for human review.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import importlib
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

EXPECTED_DATASET = "smh-rag-answer-quality-synthetic-v1"
_CITATION_PATTERN = re.compile(r"\[(?:Nguồn|Source)\s+\d+\]", re.IGNORECASE)
_RUN_MAX_CASES = 20
_RUN_MAX_MODEL_CALLS = 40
_TASK_MODEL = "openai/gpt-oss-20b"
_TASK_MAX_CASE_EXECUTIONS = 20
_TASK_MAX_PROVIDER_ATTEMPTS = 40
_TASK_MAX_INPUT_TOKENS = 100_000
_TASK_MAX_OUTPUT_TOKENS = 15_000
_PER_REQUEST_MAX_OUTPUT_TOKENS = 512
_RUN_TIMEOUT_SECONDS = 1800
_EVALUATION_SOURCE_FILES = (
    "app/services/conversation_graph.py",
    "app/rag/serving.py",
    "app/rag/retriever.py",
    "app/rag/answer_guard.py",
    "app/rag/prompt_builder.py",
    "app/rag/llm_caller.py",
    "scripts/rag_synthetic_context_factory.py",
    "scripts/evaluate_rag_answer_generation.py",
)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _question_text(case: dict[str, Any]) -> str:
    labels = {"user": "Khách", "assistant": "Trợ lý"}
    return "\n".join(
        f"{labels.get(turn['role'], turn['role'])}: {turn['content']}"
        for turn in case.get("conversation", [])
    )


def _dataset_snapshot(rows: list[dict[str, Any]], dataset_path: Path | None = None) -> dict[str, Any]:
    if dataset_path is not None:
        dataset_bytes = dataset_path.read_bytes()
        dataset_hash = hashlib.sha256(dataset_bytes).hexdigest()
    else:
        canonical_rows = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n"
            for row in rows
        ).encode("utf-8")
        dataset_hash = hashlib.sha256(canonical_rows).hexdigest()

    evidence_manifest: dict[str, dict[str, str]] = {}
    for case in rows:
        refs = case.get("evidence") or {}
        evidence_manifest[str(case["case_id"])] = {
            str(ref): _canonical_hash(value) for ref, value in sorted(refs.items())
        }
    evidence_hash = _canonical_hash(evidence_manifest)
    return {
        "dataset": EXPECTED_DATASET,
        "dataset_sha256": dataset_hash,
        "evidence_snapshot_id": f"{EXPECTED_DATASET}-evidence:{evidence_hash[:16]}",
        "evidence_snapshot_sha256": evidence_hash,
        "evidence_manifest": evidence_manifest,
    }


def _implementation_snapshot() -> dict[str, Any]:
    files = {}
    for relative in _EVALUATION_SOURCE_FILES:
        path = BACKEND_DIR / relative
        if path.is_file():
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"files": files, "sha256": _canonical_hash(files)}


def _review_source_ids(captured_evidence: list[dict[str, Any]], graph_trace: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for item in captured_evidence:
        metadata = item.get("metadata")
        source_id = metadata.get("synthetic_evidence_id") if isinstance(metadata, dict) else None
        if source_id and str(source_id) not in ids:
            ids.append(str(source_id))
    for item in graph_trace.get("evidence_manifest") or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        digest = str(item.get("sha256") or "").strip()
        if source == "CURRENT_REQUEST_REQUIREMENTS" or not source or not digest:
            continue
        source_id = f"{source}:{digest}"
        if source_id not in ids:
            ids.append(source_id)
    return ids


def _sampling_config(*, uses_application_graph: bool) -> dict[str, Any]:
    if not uses_application_graph:
        return {"invoker": "test-only; no provider request"}
    return {
        "provider": "groq",
        "model": _TASK_MODEL,
        "temperature": 0.3,
        "retrieval_mode": "bm25",
        "provider_fallback": False,
        "max_retries": 0,
        "max_completion_tokens_per_request": _PER_REQUEST_MAX_OUTPUT_TOKENS,
        "max_model_calls_per_run": _RUN_MAX_MODEL_CALLS,
        "sales_journey_engine_enabled": False,
    }


@dataclass
class EvaluationContext:
    """Disposable application context supplied by a synthetic fixture factory."""

    db: Any
    business_id: int
    conversation: Any
    synthetic: bool
    read_only: bool
    platform_db: Any = None
    industry_config: dict[str, Any] | None = None


@dataclass
class SyntheticNotificationAdapter:
    """Evaluation-only notification boundary that records intent, never persists it."""

    context: EvaluationContext
    intents: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.intents is None:
            self.intents = []

    def _assert_safe_context(self, db) -> None:
        if self.context.synthetic is not True or self.context.read_only is not True:
            raise PermissionError("synthetic_notification_adapter_requires_read_only_synthetic_context")
        if db is not self.context.db:
            raise PermissionError("synthetic_notification_adapter_database_mismatch")
        bind = db.get_bind()
        if bind.dialect.name != "sqlite":
            raise PermissionError("synthetic_notification_adapter_requires_sqlite")
        databases = db.connection().exec_driver_sql("PRAGMA database_list").fetchall()
        if any(str(row[2] or "").strip() for row in databases):
            raise PermissionError("synthetic_notification_adapter_database_must_be_in_memory")
        query_only = bool(db.connection().exec_driver_sql("PRAGMA query_only").scalar())
        if not query_only:
            raise PermissionError("synthetic_notification_adapter_requires_query_only")

    def record(
        self,
        db,
        *,
        conversation,
        business_id: int,
        query_text: str,
        reason: str,
        idempotency_key: str | None = None,
    ) -> bool:
        """Capture a handoff request; false means deliberately not persisted."""
        self._assert_safe_context(db)
        if business_id != self.context.business_id:
            raise PermissionError("synthetic_notification_adapter_tenant_mismatch")
        conversation_business_id = getattr(conversation, "business_id", business_id)
        if conversation_business_id != business_id:
            raise PermissionError("synthetic_notification_adapter_conversation_tenant_mismatch")
        self.intents.append({
            "business_id": business_id,
            "conversation_id": getattr(conversation, "id", None),
            "query_text": str(query_text),
            "reason": str(reason),
            "idempotency_key": idempotency_key,
            "persisted": False,
            "database_write_attempted": False,
            "external_message_attempted": False,
        })
        # Recheck after capture so a future implementation cannot quietly
        # disable query_only during the adapter call.
        self._assert_safe_context(db)
        return False


class EvaluationBudgetExceeded(RuntimeError):
    """An evaluation-only provider allowance was exhausted before an API request."""


class _ProviderBudget:
    """Persistent, conservative budget shared by baseline and post-fix runs.

    Before each Groq request, input tokens are reserved using a conservative
    UTF-8 byte upper bound and output tokens are capped in the API request.
    Successful provider usage reconciles reservations down to reported counts;
    failed or unreported attempts keep their full reservation.
    """

    _LOCKS: dict[str, threading.RLock] = {}
    _LOCKS_GUARD = threading.Lock()

    def __init__(self, ledger_path: Path, phase: str, cases: list[dict[str, Any]]):
        if phase not in {"baseline", "post-fix"}:
            raise ValueError("evaluation_phase_invalid")
        self.path = ledger_path
        self.phase = phase
        self.case_ids = [str(case["case_id"]) for case in cases]
        self._active_reservations: dict[int, dict[str, int]] = {}
        self._next_reservation = 1
        self._actual = {"input_tokens": 0, "output_tokens": 0}
        self._unknown_usage_attempts = 0
        self._lock = self._thread_lock(str(self.path.resolve()))
        self._file_handle = None
        self._acquire_process_lock()
        try:
            self.ledger = self._read_or_initialize()
            self._register_run()
        except BaseException:
            self._release_process_lock()
            raise

    @classmethod
    def _thread_lock(cls, key: str) -> threading.RLock:
        with cls._LOCKS_GUARD:
            return cls._LOCKS.setdefault(key, threading.RLock())

    def _acquire_process_lock(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._file_handle = lock_path.open("a+b")
        self._lock.acquire()
        try:
            if os.name == "nt":
                import msvcrt
                self._file_handle.seek(0)
                if self._file_handle.read(1) == b"":
                    self._file_handle.seek(0)
                    self._file_handle.write(b"0")
                    self._file_handle.flush()
                self._file_handle.seek(0)
                msvcrt.locking(self._file_handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file_handle.fileno(), fcntl.LOCK_EX)
        except BaseException:
            self._file_handle.close()
            self._file_handle = None
            self._lock.release()
            raise

    def _release_process_lock(self) -> None:
        if self._file_handle is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._file_handle.seek(0)
                    msvcrt.locking(self._file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._file_handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._file_handle.close()
                self._file_handle = None
                self._lock.release()

    def close(self) -> None:
        self._release_process_lock()

    def _read_or_initialize(self) -> dict[str, Any]:
        limits = {
            "case_executions": _TASK_MAX_CASE_EXECUTIONS,
            "physical_attempts": _TASK_MAX_PROVIDER_ATTEMPTS,
            "input_tokens": _TASK_MAX_INPUT_TOKENS,
            "output_tokens": _TASK_MAX_OUTPUT_TOKENS,
        }
        if self.path.exists():
            try:
                ledger = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise PermissionError("evaluation_budget_ledger_invalid") from None
            if ledger.get("schema_version") != 1 or ledger.get("limits") != limits:
                raise PermissionError("evaluation_budget_ledger_mismatch")
            if not isinstance(ledger.get("consumed"), dict) or not isinstance(ledger.get("runs"), list):
                raise PermissionError("evaluation_budget_ledger_invalid")
            return ledger
        return {
            "schema_version": 1,
            "limits": limits,
            "consumed": {
                "case_executions": 0,
                "physical_attempts": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            },
            "reported_usage": {"input_tokens": 0, "output_tokens": 0},
            "runs": [],
        }

    def _persist(self) -> None:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self.ledger, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

    def _register_run(self) -> None:
        if any(item.get("phase") == self.phase for item in self.ledger["runs"]):
            raise PermissionError(f"evaluation_phase_already_consumed:{self.phase}")
        if self.phase == "baseline" and len(self.case_ids) != _RUN_MAX_CASES:
            raise ValueError("baseline_requires_all_20_cases")
        if len(self.case_ids) > _RUN_MAX_CASES:
            raise ValueError(f"provider_evaluation_case_limit_exceeded:{_RUN_MAX_CASES}")
        if len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("evaluation_case_ids_must_be_unique")
        consumed = self.ledger["consumed"]
        if consumed["case_executions"] + len(self.case_ids) > _TASK_MAX_CASE_EXECUTIONS:
            raise EvaluationBudgetExceeded("case_executions")
        if not self.ledger["runs"] and self.phase != "baseline":
            raise PermissionError("post_fix_run_requires_baseline")
        if self.ledger["runs"] and self.phase != "post-fix":
            raise PermissionError("baseline_run_already_recorded")
        self.ledger["consumed"]["case_executions"] += len(self.case_ids)
        self.ledger["runs"].append({"phase": self.phase, "case_ids": self.case_ids})
        self._persist()

    @staticmethod
    def _prompt_upper_bound(model: str, messages: Any, request_fields: dict[str, Any]) -> int:
        payload = {"model": model, "messages": messages}
        for name in ("response_format", "tools", "tool_choice", "parallel_tool_calls"):
            if name in request_fields:
                payload[name] = request_fields[name]
        encoded_bytes = len(json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8"))
        message_count = len(messages) if isinstance(messages, list) else 1
        # 2x byte count plus chat framing allowance is deliberately conservative
        # and avoids an unverified model tokenizer dependency.
        return (encoded_bytes * 2) + max(512, 128 * message_count)

    def reserve_request(self, kwargs: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        model = str(kwargs.get("model") or "")
        if model != _TASK_MODEL:
            raise PermissionError("evaluation_model_not_approved")
        if kwargs.get("stream"):
            raise PermissionError("streaming_not_allowed_in_bounded_evaluation")
        consumed = self.ledger["consumed"]
        if consumed["physical_attempts"] >= _TASK_MAX_PROVIDER_ATTEMPTS:
            raise EvaluationBudgetExceeded("physical_attempts")
        input_reserve = self._prompt_upper_bound(model, kwargs.get("messages"), kwargs)
        if consumed["input_tokens"] + input_reserve > _TASK_MAX_INPUT_TOKENS:
            raise EvaluationBudgetExceeded("input_tokens")
        output_reserve = min(
            _PER_REQUEST_MAX_OUTPUT_TOKENS,
            _TASK_MAX_OUTPUT_TOKENS - consumed["output_tokens"],
        )
        if output_reserve <= 0:
            raise EvaluationBudgetExceeded("output_tokens")

        kwargs.pop("max_tokens", None)
        kwargs["max_completion_tokens"] = output_reserve
        reservation_id = self._next_reservation
        self._next_reservation += 1
        self._active_reservations[reservation_id] = {
            "input_tokens": input_reserve,
            "output_tokens": output_reserve,
        }
        consumed["physical_attempts"] += 1
        consumed["input_tokens"] += input_reserve
        consumed["output_tokens"] += output_reserve
        self._persist()
        return reservation_id, kwargs

    @staticmethod
    def _reported_usage(response: Any) -> tuple[int, int] | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
        if isinstance(usage, dict):
            prompt = usage.get("prompt_tokens", prompt)
            completion = usage.get("completion_tokens", completion)
        if type(prompt) is not int or type(completion) is not int or prompt < 0 or completion < 0:
            return None
        return prompt, completion

    def settle_success(self, reservation_id: int, response: Any) -> None:
        reservation = self._active_reservations.pop(reservation_id)
        usage = self._reported_usage(response)
        if usage is None:
            self._unknown_usage_attempts += 1
            self._persist()
            return
        input_tokens, output_tokens = usage
        if input_tokens > reservation["input_tokens"] or output_tokens > reservation["output_tokens"]:
            self._persist()
            raise PermissionError("provider_usage_exceeded_reserved_token_bound")
        consumed = self.ledger["consumed"]
        consumed["input_tokens"] -= reservation["input_tokens"] - input_tokens
        consumed["output_tokens"] -= reservation["output_tokens"] - output_tokens
        reported = self.ledger["reported_usage"]
        reported["input_tokens"] += input_tokens
        reported["output_tokens"] += output_tokens
        self._actual["input_tokens"] += input_tokens
        self._actual["output_tokens"] += output_tokens
        self._persist()

    def snapshot(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "limits": dict(self.ledger["limits"]),
            "consumed_total": dict(self.ledger["consumed"]),
            "reported_total": dict(self.ledger["reported_usage"]),
            "unreported_usage_attempts_current_run": self._unknown_usage_attempts,
            "current_run_reported_usage": dict(self._actual),
        }


class _BoundedCompletions:
    def __init__(self, delegate: Any, budget: _ProviderBudget):
        self._delegate = delegate
        self._budget = budget

    def create(self, **kwargs):
        reservation_id, bounded_kwargs = self._budget.reserve_request(kwargs)
        try:
            response = self._delegate.create(**bounded_kwargs)
        except BaseException:
            # Keep the full reservation for uncertain provider errors.
            raise
        self._budget.settle_success(reservation_id, response)
        return response


class _BoundedGroqClient:
    def __init__(self, delegate: Any, budget: _ProviderBudget):
        from types import SimpleNamespace
        self.chat = SimpleNamespace(completions=_BoundedCompletions(delegate.chat.completions, budget))


def read_cases(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    validate_cases(rows)
    return rows


def validate_cases(cases: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(cases)
    if not rows:
        raise ValueError("answer_evaluation_cases_empty")
    for index, case in enumerate(rows):
        if not isinstance(case, dict) or case.get("dataset") != EXPECTED_DATASET:
            raise ValueError(f"case_{index}_not_from_approved_synthetic_dataset")
        if not str(case.get("tenant") or "").startswith("synthetic-"):
            raise ValueError(f"case_{index}_tenant_not_marked_synthetic")
        turns = case.get("conversation")
        if not isinstance(turns, list) or not turns:
            raise ValueError(f"case_{index}_conversation_missing")
        if any(
            not isinstance(turn, dict)
            or turn.get("role") not in {"user", "assistant"}
            or not isinstance(turn.get("content"), str)
            for turn in turns
        ):
            raise ValueError(f"case_{index}_conversation_invalid")
        if not any(turn["role"] == "user" for turn in turns):
            raise ValueError(f"case_{index}_user_turn_missing")
        if not isinstance(case.get("gold"), dict) or not isinstance(case.get("evidence"), dict):
            raise ValueError(f"case_{index}_gold_or_evidence_missing")
    return rows


def validate_context(context: EvaluationContext) -> None:
    required_fields = ("db", "business_id", "conversation", "synthetic", "read_only", "platform_db")
    if context is None or any(not hasattr(context, name) for name in required_fields):
        raise ValueError("evaluation_context_contract_invalid")
    if context.synthetic is not True:
        raise ValueError("evaluation_context_must_be_explicitly_synthetic")
    if context.read_only is not True:
        raise ValueError("evaluation_context_must_be_read_only")
    if context.platform_db is not None:
        raise ValueError("platform_database_context_forbidden")
    if type(context.business_id) is not int or context.business_id <= 0:
        raise ValueError("evaluation_business_id_invalid")

    bind = context.db.get_bind()
    if bind.dialect.name != "sqlite":
        raise ValueError("evaluation_database_must_be_sqlite_memory")
    rows = context.db.connection().exec_driver_sql("PRAGMA database_list").fetchall()
    if any(str(row[2] or "").strip() for row in rows):
        raise ValueError("evaluation_database_must_not_be_file_backed")
    context.db.connection().exec_driver_sql("PRAGMA query_only=ON")


def _case_query(case: dict[str, Any]) -> str:
    query = next(turn["content"] for turn in reversed(case["conversation"]) if turn["role"] == "user")
    for evidence_id, evidence in (case.get("evidence") or {}).items():
        if evidence_id.startswith("image-observation:") and isinstance(evidence, dict):
            query += (
                "\nVISIBLE_IMAGE_OBSERVATION: "
                f"{evidence.get('ocr_text', '')} (confidence {evidence.get('confidence', 'unknown')})"
            )
    return query


def classify_pipeline_outcome(result, error_type, model_invocations, attempts) -> str:
    """Classify execution provenance; never infer model reasoning from answer text alone."""
    status_codes = {
        str(item.get("status_code") or "").strip()
        for item in attempts
        if isinstance(item, dict)
    }
    if "429" in status_codes or any(
        str(item.get("error_type") or "").strip() == "RateLimitError"
        for item in attempts
        if isinstance(item, dict)
    ):
        # A graph may catch a provider 429 and return a deterministic safe reply.
        # Preserve that reply, but classify the run as rate-limited so the outer
        # evaluation loop stops before creating contexts for subsequent cases.
        return "PROVIDER_RATE_LIMIT_429"
    if result is None:
        if error_type == "ProviderCircuitOpen" or any(
            item.get("error_type") == "ProviderCircuitOpen" for item in attempts if isinstance(item, dict)
        ):
            return "CIRCUIT_OPEN"
        if "400" in status_codes or error_type == "BadRequestError":
            return "PROVIDER_HTTP_400"
        if error_type == "RateLimitError":
            return "PROVIDER_RATE_LIMIT_429"
        return "INFRASTRUCTURE_ERROR"

    status = str(getattr(result, "status", "") or "").strip().lower()
    metadata = getattr(result, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    action = str(metadata.get("action") or getattr(result, "action", "") or "").strip().lower()
    if (
        "clarification" in status
        or status in {"calendar_subject_needed", "missing_required_slot", "ask_clarification"}
        or action in {"clarify", "ask_clarification"}
    ):
        return "CLARIFICATION"
    if metadata.get("validated_fallback") is True:
        return "VALIDATED_FALLBACK"

    # A successful planner, query-rewriter, or arithmetic call does not prove
    # the user-visible answer was generated by a model. Count only the
    # validated structured answer contract used by the graph's final composer.
    answer_invocations = [
        item for item in model_invocations
        if isinstance(item, dict)
        and item.get("schema_name") == "shop_answer"
        and item.get("response_text")
        and item.get("error_type") is None
        and item.get("parse_status") == "passed"
        and item.get("validation_status") == "passed"
    ]
    if status == "graph_answer" and answer_invocations:
        if any(
            item.get("route_kind") == "fallback"
            for item in answer_invocations
        ):
            return "VALIDATED_FALLBACK"
        return "LLM_GENERATED_ANSWER"

    if str(getattr(result, "prompt", "") or "").strip():
        return "DETERMINISTIC_ANSWER"
    return "INFRASTRUCTURE_ERROR"


def _default_graph_invoker(db, *, business_id, conversation, query, job_key, platform_db=None, industry_config=None):
    from app.services.conversation_graph import graph_reply

    # Importing the graph may lazily import app database engines. Re-check
    # after that import and immediately before the graph can issue any work.
    _assert_imported_engines_are_ephemeral()
    return graph_reply(
        db,
        business_id=business_id,
        conversation=conversation,
        query=query,
        job_key=job_key,
        platform_db=platform_db,
        industry_config=industry_config,
    )


def _evaluate_case(
    case,
    context,
    invocation,
    serving,
    trace_path,
    *,
    snapshot_id: str = "unversioned-test-snapshot",
    snapshot_sha256: str = "0" * 64,
    model: str = "TEST_INVOKER; no provider model",
    sampling_config: dict[str, Any] | None = None,
    provider_execution_enabled: bool = False,
) -> dict[str, Any]:
    from unittest.mock import patch
    from sqlalchemy import event as sqlalchemy_event

    captured_evidence: list[dict[str, Any]] = []
    notification_adapter = SyntheticNotificationAdapter(context)
    original_retrieve = serving.retrieve_shop_knowledge

    def capture_retrieval(**kwargs):
        chunks = original_retrieve(**kwargs)
        for chunk in chunks:
            captured_evidence.append({
                "chunk_id": getattr(chunk, "chunk_id", None),
                "document_id": getattr(chunk, "document_id", None),
                "content": getattr(chunk, "content", ""),
                "filename": getattr(chunk, "filename", None),
                "similarity": getattr(chunk, "similarity", None),
                "metadata": getattr(chunk, "metadata", None),
            })
        return chunks

    started = time.perf_counter()
    trace_offset = trace_path.stat().st_size if trace_path.exists() else 0
    error_type = None
    result = None
    attempted_write_models: set[str] = set()
    executed_write_models: set[str] = set()
    pending_flush_models: set[str] = set()

    def _record_models(target, bucket):
        for collection in (target.new, target.dirty, target.deleted):
            bucket.update(type(row).__name__ for row in collection)

    def _before_flush(target, _flush_context, _instances):
        _record_models(target, attempted_write_models)
        pending_flush_models.update(type(row).__name__ for group in (target.new, target.dirty, target.deleted) for row in group)

    def _after_flush(target, _flush_context):
        executed_write_models.update(pending_flush_models)
        pending_flush_models.clear()

    sqlalchemy_event.listen(context.db, "before_flush", _before_flush)
    sqlalchemy_event.listen(context.db, "after_flush", _after_flush)
    model_invocations = []
    try:
        # Context validation normally happens in run_evaluation. Keep the
        # boundary fail-closed if this helper is called directly by a test or
        # another offline tool.
        notification_adapter._assert_safe_context(context.db)
        import app.rag.llm_caller as llm_caller
        with llm_caller.capture_llm_trace() as model_invocations:
            with patch("app.services.auto_reply_service._record_rag_handoff", side_effect=notification_adapter.record), \
                 patch("app.rag.serving.retrieve_shop_knowledge", side_effect=capture_retrieval):
                result = invocation(
                    context.db,
                    business_id=context.business_id,
                    conversation=context.conversation,
                    query=_case_query(case),
                    job_key=f"synthetic-eval:{case['case_id']}",
                    platform_db=None,
                    industry_config=context.industry_config,
                )
    except Exception as error:  # retain a safe classification, not exception text
        error_type = type(error).__name__
    finally:
        sqlalchemy_event.remove(context.db, "before_flush", _before_flush)
        sqlalchemy_event.remove(context.db, "after_flush", _after_flush)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    traces = []
    if trace_path.exists():
        with trace_path.open("r", encoding="utf-8") as handle:
            handle.seek(trace_offset)
            for line in handle:
                try:
                    traces.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    graph_trace = next((item for item in reversed(traces)
                        if item.get("operation") == "conversation_graph"), {})
    attempts = graph_trace.get("attempt_records") or []
    model_invocations = list(model_invocations) if isinstance(model_invocations, list) else []
    usage_rows = [item.get("usage") or {} for item in attempts]
    token_totals = {
        key: sum(int(usage.get(key) or 0) for usage in usage_rows)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    answer = str(getattr(result, "prompt", "") or "")
    pipeline_outcome = classify_pipeline_outcome(result, error_type, model_invocations, attempts)
    question = _question_text(case)
    token_count = token_totals["total_tokens"] if any(token_totals.values()) else None
    logical_calls = graph_trace.get("calls")
    ranked_source_ids = _review_source_ids(captured_evidence, graph_trace)
    query_only = False
    database_ephemeral = False
    try:
        bind = context.db.get_bind()
        database_ephemeral = bind.dialect.name == "sqlite" and not any(
            str(row[2] or "").strip()
            for row in context.db.connection().exec_driver_sql("PRAGMA database_list").fetchall()
        )
        query_only = bool(context.db.connection().exec_driver_sql("PRAGMA query_only").scalar())
    except Exception:
        pass
    return {
        "case_id": case["case_id"],
        "tenant": case["tenant"],
        "business_id": context.business_id,
        "question": question,
        "question_hash": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "snapshot_id": snapshot_id,
        "snapshot_sha256": snapshot_sha256,
        "model": model,
        "sampling_config": sampling_config or {"invoker": "test-only; no provider request"},
        "answer": answer,
        "execution_status": "EXECUTED",
        "ranked_source_ids": ranked_source_ids,
        "fallback_used": pipeline_outcome == "VALIDATED_FALLBACK",
        "tokens": token_count,
        "llm_calls": logical_calls if isinstance(logical_calls, int) else len(model_invocations),
        "input_conversation": case["conversation"],
        "effective_query": _case_query(case),
        "tenant_business_id": context.business_id,
        "retrieved_evidence": captured_evidence,
        "evidence_ids_used": graph_trace.get("evidence_manifest") or graph_trace.get("authoritative_source_ids") or graph_trace.get("source_ids") or [],
        "selected_tools": graph_trace.get("tools"),
        "tool_status": graph_trace.get("tool_status"),
        "pipeline_outcome": pipeline_outcome,
        "model_invocations": model_invocations,
        "model_text": [item.get("response_text") for item in model_invocations if item.get("response_text")],
        "generated_response": answer,
        "citations": _CITATION_PATTERN.findall(answer),
        "expected_claims": case["gold"].get("required_claims", []),
        "expected_evidence_ids": case["gold"].get("evidence_ids", []),
        "expected_action": case["gold"].get("action"),
        "correctness": "NOT_MEASURED; requires human/approved judge review",
        "groundedness": "NOT_MEASURED; requires citation-to-evidence review",
        "unsupported_claims": "NOT_MEASURED; requires answer claim annotation",
        "context_retention": "NOT_MEASURED; label only multi-turn cases",
        "safe_tool_behavior": graph_trace.get("capability_authorization", "NOT_CAPTURED"),
        "execution_safety": {
            "synthetic_context": context.synthetic is True,
            "in_memory_sqlite": database_ephemeral,
            "database_query_only": query_only,
            "platform_database_unavailable": context.platform_db is None,
            "external_customer_channel_invoked": False,
        },
        "application_status": getattr(result, "status", None),
        "notification_intents": list(notification_adapter.intents or []),
        "staff_decision_intents": [
            {"reason": intent["reason"], "conversation_id": intent["conversation_id"]}
            for intent in (notification_adapter.intents or [])
        ],
        "error_type": error_type,
        "provider_attempt_records": attempts,
        "retry_circuit_transitions": [
            {key: item.get(key) for key in ("provider", "model", "route_kind", "error_type", "status_code", "circuit_state_before", "circuit_state_after")}
            for event in model_invocations if isinstance(event, dict)
            for item in (event.get("routes") or [event]) if isinstance(item, dict)
        ],
        "side_effects": {
            "attempted_database_models": sorted(attempted_write_models),
            "flushed_database_models": sorted(executed_write_models),
            "external_customer_channel_attempted": False,
            "external_customer_channel_executed": False,
            "notification_database_write_attempted": any(
                intent["database_write_attempted"] for intent in (notification_adapter.intents or [])
            ),
            "notification_external_message_attempted": any(
                intent["external_message_attempted"] for intent in (notification_adapter.intents or [])
            ),
        },
        "latency_ms": elapsed_ms,
        "model_logical_calls": logical_calls,
        "model_physical_attempts": len(attempts) if attempts else None,
        "token_usage": token_totals if any(token_totals.values()) else "NOT_REPORTED_BY_PROVIDER",
        "cost": "NOT_MEASURED; provider pricing not configured in evaluator",
        "provider_calls_authorized": provider_execution_enabled,
        "provider_calls_made": bool(attempts),
        "synthetic_only": True,
    }


def _not_executed_after_rate_limit(
    case: dict[str, Any],
    *,
    snapshot_id: str,
    snapshot_sha256: str,
    model: str,
    sampling_config: dict[str, Any],
) -> dict[str, Any]:
    """Keep every frozen case visible without dispatching after provider 429."""
    question = _question_text(case)
    return {
        "case_id": case["case_id"],
        "tenant": case["tenant"],
        "business_id": None,
        "question": question,
        "question_hash": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "snapshot_id": snapshot_id,
        "snapshot_sha256": snapshot_sha256,
        "model": model,
        "sampling_config": sampling_config,
        "answer": None,
        "execution_status": "NOT_EXECUTED",
        "pipeline_outcome": "NOT_EXECUTED_AFTER_PROVIDER_RATE_LIMIT",
        "halt_reason": "PROVIDER_RATE_LIMIT_429",
        "ranked_source_ids": [],
        "fallback_used": False,
        "tokens": None,
        "llm_calls": 0,
        "input_conversation": case["conversation"],
        "effective_query": _case_query(case),
        "provider_attempt_records": [],
        "provider_calls_authorized": True,
        "provider_calls_made": False,
        "synthetic_only": True,
    }


def run_evaluation(
    cases: Iterable[dict[str, Any]],
    context_factory: Callable[[dict[str, Any]], EvaluationContext],
    *,
    output_path: Path,
    provider_calls_allowed: bool = False,
    invoke_graph: Callable[..., Any] | None = None,
    phase: str = "baseline",
    budget_ledger_path: Path | None = None,
    dataset_path: Path | None = None,
) -> dict[str, Any]:
    """Invoke graph_reply sequentially and persist raw, reviewable synthetic results."""
    rows = validate_cases(cases)
    snapshot = _dataset_snapshot(rows, dataset_path)
    implementation_snapshot = _implementation_snapshot()
    if len(rows) > _RUN_MAX_CASES:
        raise ValueError(f"provider_evaluation_case_limit_exceeded:{_RUN_MAX_CASES}")
    if provider_calls_allowed is not True:
        raise PermissionError("provider_evaluation_requires_explicit_owner_approval")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path = output_path.with_suffix(".rag-runs.jsonl")
    results: list[dict[str, Any]] = []
    suppressed_provider_attempts: list[str] = []
    halt_reason = None
    provider_budget = None
    with _ephemeral_database_settings() as settings:
        import app.rag.serving as serving
        from app.rag.turn_budget import turn_budget
        from unittest.mock import patch
        from contextlib import ExitStack

        _assert_database_settings_are_ephemeral(settings)
        if settings.SALES_JOURNEY_ENGINE_ENABLED:
            raise PermissionError("evaluation_requires_sales_journey_engine_disabled")
        uses_application_graph = invoke_graph is None
        if uses_application_graph:
            if not settings.groq_api_keys:
                raise PermissionError("provider_blocked_groq_test_credential_missing")
            if output_path.exists() or trace_path.exists():
                raise PermissionError("evaluation_output_exists_refusing_overwrite")
            _assert_imported_engines_are_ephemeral()
            ledger_path = budget_ledger_path or (
                BACKEND_DIR.parent / "reports" / "rag-intelligence-final" / "provider-budget-ledger-answer-quality-v1.json"
            )
            provider_budget = _ProviderBudget(ledger_path, phase, rows)
            previous_provider_settings = {
                name: getattr(settings, name)
                for name in (
                    "LLM_PROVIDER", "LLM_MODEL", "RAG_RETRIEVAL_MODE",
                    "GEMINI_FALLBACK_MODEL", "GEMINI_FALLBACK_MODELS",
                )
            }
            # The task authorizes exactly one text provider/model. BM25 keeps
            # the synthetic SQLite path offline from the configured Gemini embedder.
            settings.LLM_PROVIDER = "groq"
            settings.LLM_MODEL = _TASK_MODEL
            settings.RAG_RETRIEVAL_MODE = "bm25"
            settings.GEMINI_FALLBACK_MODEL = ""
            settings.GEMINI_FALLBACK_MODELS = ""
        else:
            provider_budget = None
            previous_provider_settings = None
        review_model = f"groq/{_TASK_MODEL}" if uses_application_graph else "TEST_INVOKER; no provider model"
        review_sampling_config = _sampling_config(uses_application_graph=uses_application_graph)
        invocation = invoke_graph or _default_graph_invoker
        previous_log_path = settings.RAG_LOG_FILE
        settings.RAG_LOG_FILE = str(trace_path)
        try:
            # Quota accounting is the only suppressed DB write. App data is held
            # in query-only, disposable SQLite; no order/payment/appointment
            # capability is enabled in the synthetic fixture.
            try:
                with ExitStack() as stack:
                    stack.enter_context(patch("app.services.quota_service.record_quota_usage", lambda *_args, **_kwargs: None))
                    if uses_application_graph:
                        import app.rag.llm_caller as llm_caller
                        import app.rag.embedder as embedder
                        import app.rag.retriever as retriever
                        original_groq_client = llm_caller._groq_client

                        def reject_non_groq(provider_name: str):
                            def reject(*_args, **_kwargs):
                                suppressed_provider_attempts.append(provider_name)
                                raise PermissionError("evaluation_provider_not_approved")
                            return reject

                        stack.enter_context(patch.object(
                            llm_caller, "_groq_model_routes",
                            lambda **_kwargs: [("groq", _TASK_MODEL)],
                        ))
                        stack.enter_context(patch.object(
                            llm_caller, "_groq_client",
                            lambda api_key=None: _BoundedGroqClient(
                                original_groq_client(api_key), provider_budget,
                            ),
                        ))
                        stack.enter_context(patch.object(
                            llm_caller, "call_gemini", reject_non_groq("gemini_llm"),
                        ))
                        stack.enter_context(patch.object(
                            llm_caller, "call_openai", reject_non_groq("openai_llm"),
                        ))
                        stack.enter_context(patch.object(
                            retriever, "embed_query", reject_non_groq("non_groq_embedding"),
                        ))
                        stack.enter_context(patch.object(
                            embedder, "embed_query", reject_non_groq("non_groq_embedding"),
                        ))
                    remaining_attempts = (
                        _TASK_MAX_PROVIDER_ATTEMPTS - provider_budget.ledger["consumed"]["physical_attempts"]
                        if provider_budget else _TASK_MAX_PROVIDER_ATTEMPTS
                    )
                    with turn_budget(
                        timeout_seconds=_RUN_TIMEOUT_SECONDS,
                        max_calls=min(_RUN_MAX_MODEL_CALLS, remaining_attempts),
                        max_attempts=remaining_attempts,
                        max_provider_switches=0,
                    ) as run_budget:
                        for case_index, case in enumerate(rows):
                            context = context_factory(case)
                            try:
                                validate_context(context)
                                _assert_database_settings_are_ephemeral(settings)
                                if uses_application_graph:
                                    _assert_imported_engines_are_ephemeral()
                                case_result = _evaluate_case(
                                    case,
                                    context,
                                    invocation,
                                    serving,
                                    trace_path,
                                    snapshot_id=snapshot["evidence_snapshot_id"],
                                    snapshot_sha256=snapshot["evidence_snapshot_sha256"],
                                    model=review_model,
                                    sampling_config=review_sampling_config,
                                    provider_execution_enabled=uses_application_graph,
                                )
                                results.append(case_result)
                            finally:
                                db = getattr(context, "db", None)
                                bind = None
                                try:
                                    bind = db.get_bind() if db is not None else None
                                except Exception:
                                    pass
                                close = getattr(db, "close", None)
                                if callable(close):
                                    close()
                                if getattr(getattr(bind, "dialect", None), "name", None) == "sqlite":
                                    bind.dispose()
                            if case_result.get("pipeline_outcome") == "PROVIDER_RATE_LIMIT_429":
                                halt_reason = "PROVIDER_RATE_LIMIT_429"
                                results.extend(
                                    _not_executed_after_rate_limit(
                                        pending_case,
                                        snapshot_id=snapshot["evidence_snapshot_id"],
                                        snapshot_sha256=snapshot["evidence_snapshot_sha256"],
                                        model=review_model,
                                        sampling_config=review_sampling_config,
                                    )
                                    for pending_case in rows[case_index + 1:]
                                )
                                break
                        run_budget_summary = run_budget.snapshot()
            finally:
                if provider_budget:
                    provider_budget.close()
                if previous_provider_settings is not None:
                    for name, value in previous_provider_settings.items():
                        setattr(settings, name, value)
        finally:
            settings.RAG_LOG_FILE = previous_log_path

    report = {
        "dataset": EXPECTED_DATASET,
        "dataset_sha256": snapshot["dataset_sha256"],
        "snapshot_id": snapshot["evidence_snapshot_id"],
        "snapshot_sha256": snapshot["evidence_snapshot_sha256"],
        "source_snapshot": snapshot["evidence_manifest"],
        "implementation_snapshot": implementation_snapshot,
        "execution_path": "app.services.conversation_graph.graph_reply",
        "case_count": len(results),
        "cases_executed": sum(item.get("execution_status") == "EXECUTED" for item in results),
        "case_execution_status_counts": {
            status: sum(1 for item in results if item.get("execution_status") == status)
            for status in ("EXECUTED", "NOT_EXECUTED")
        },
        "halt_reason": halt_reason,
        "provider_calls_authorized": uses_application_graph,
        "provider_calls_made": sum(bool(item.get("provider_calls_made")) for item in results),
        "model": review_model,
        "sampling_config": review_sampling_config,
        "synthetic_only": True,
        "answer_correctness": "NOT_MEASURED; no human labels/approved judge supplied",
        "answer_groundedness": "NOT_MEASURED; no citation review supplied",
        "hallucination_rate": "NOT_MEASURED; no claim annotations supplied",
        "run_limits": {
            "max_cases": _RUN_MAX_CASES,
            "max_model_calls": _RUN_MAX_MODEL_CALLS,
            "max_physical_provider_attempts": _TASK_MAX_PROVIDER_ATTEMPTS,
            "task_total_case_executions": _TASK_MAX_CASE_EXECUTIONS,
            "task_total_input_tokens": _TASK_MAX_INPUT_TOKENS,
            "task_total_output_tokens": _TASK_MAX_OUTPUT_TOKENS,
            "model": _TASK_MODEL,
            "timeout_seconds": _RUN_TIMEOUT_SECONDS,
        },
        "run_budget": run_budget_summary,
        "provider_budget": provider_budget.snapshot() if provider_budget else "NOT_APPLICABLE_TEST_INVOKER",
        "suppressed_non_groq_provider_attempts": suppressed_provider_attempts,
        "pipeline_outcome_counts": {
            name: sum(1 for item in results if item.get("pipeline_outcome") == name)
            for name in (
                "DETERMINISTIC_ANSWER", "LLM_GENERATED_ANSWER", "VALIDATED_FALLBACK", "CLARIFICATION",
                "PROVIDER_HTTP_400", "PROVIDER_RATE_LIMIT_429", "CIRCUIT_OPEN", "INFRASTRUCTURE_ERROR",
                "NOT_EXECUTED_AFTER_PROVIDER_RATE_LIMIT",
            )
        },
        "results": results,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return report


@contextmanager
def _ephemeral_database_settings():
    """Force all application database URLs to in-memory SQLite for this process scope."""
    names = ("DATABASE_URL", "TENANT_DATABASE_URL", "PLATFORM_DATABASE_URL")
    previous_env = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ[name] = "sqlite://"
    try:
        from app.core.config import settings

        previous_settings = {name: getattr(settings, name) for name in names}
        for name in names:
            setattr(settings, name, "sqlite://")
        try:
            yield settings
        finally:
            for name, value in previous_settings.items():
                setattr(settings, name, value)
    finally:
        for name, value in previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _assert_imported_engines_are_ephemeral() -> None:
    """Fail before case execution if an already-imported app engine targets a real DB."""
    for module_name in ("app.database.session", "app.database.tenant_session", "app.database.platform_session"):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for attribute in ("engine", "tenant_engine", "platform_engine"):
            engine = getattr(module, attribute, None)
            if engine is None:
                continue
            url = getattr(engine, "url", None)
            if (
                getattr(getattr(engine, "dialect", None), "name", None) != "sqlite"
                or getattr(url, "database", None) not in (None, "", ":memory:")
            ):
                raise PermissionError("application_database_engine_is_not_ephemeral_sqlite")


def _assert_database_settings_are_ephemeral(settings) -> None:
    """Fail closed unless every configured application DB URL is in-memory SQLite."""
    for name in ("DATABASE_URL", "TENANT_DATABASE_URL", "PLATFORM_DATABASE_URL"):
        value = str(getattr(settings, name, "") or "")
        if value not in {"sqlite://", "sqlite:///:memory:"}:
            raise PermissionError(f"application_database_setting_is_not_ephemeral:{name}")


def _load_factory(spec: str) -> Callable[[dict[str, Any]], EvaluationContext]:
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("context_factory_must_be_module:function")
    factory = getattr(importlib.import_module(module_name), attribute)
    if not callable(factory):
        raise ValueError("context_factory_not_callable")
    return factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=BACKEND_DIR / "test_data" / "rag_answer_quality_acceptance_v1.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context-factory", help="Synthetic adapter in module:function form")
    parser.add_argument("--allow-provider-calls", action="store_true", help="Use only after the owner separately approves provider-backed evaluation")
    parser.add_argument("--phase", choices=("baseline", "post-fix"), default="baseline")
    parser.add_argument("--budget-ledger", type=Path)
    args = parser.parse_args(argv)
    cases = read_cases(args.cases)
    if not args.allow_provider_calls:
        print(json.dumps({
            "dataset": EXPECTED_DATASET,
            "case_count": len(cases),
            "execution_path": "app.services.conversation_graph.graph_reply",
            "answer_quality": "NOT_MEASURED",
            "provider_calls": 0,
            "preflight": "PASS; no context factory imported and no app/provider/database call made",
            "next_requirement": "separate owner approval, then --allow-provider-calls and a synthetic in-memory SQLite context factory",
        }, ensure_ascii=False, indent=2))
        return 0
    if not args.context_factory:
        parser.error("--context-factory is required when --allow-provider-calls is set")
    factory_spec = args.context_factory
    factory_holder: list[Callable[[dict[str, Any]], EvaluationContext]] = []

    def lazy_factory(case):
        if not factory_holder:
            factory_holder.append(_load_factory(factory_spec))
        return factory_holder[0](case)

    report = run_evaluation(
        cases,
        lazy_factory,
        output_path=args.output,
        provider_calls_allowed=True,
        phase=args.phase,
        budget_ledger_path=args.budget_ledger,
        dataset_path=args.cases,
    )
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
