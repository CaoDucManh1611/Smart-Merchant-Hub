from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scripts.evaluate_rag_answer_generation import (
    EvaluationContext,
    EvaluationBudgetExceeded,
    SyntheticNotificationAdapter,
    _ProviderBudget,
    _evaluate_case,
    _assert_database_settings_are_ephemeral,
    _assert_imported_engines_are_ephemeral,
    _case_query,
    classify_pipeline_outcome,
    _dataset_snapshot,
    _ephemeral_database_settings,
    main,
    read_cases,
    run_evaluation,
    validate_cases,
    validate_context,
)


def _create_sqlite_engine(*args, **kwargs):
    """Keep synthetic evaluation DBs ephemeral even in PostgreSQL CI runs."""
    engine_factory = getattr(create_engine, "_smh_original_create_engine", create_engine)
    return engine_factory(*args, **kwargs)


@pytest.mark.parametrize(
    ("result", "error_type", "model_invocations", "attempts", "expected"),
    [
        (SimpleNamespace(status="product_fact", prompt="price", answer="price", metadata={}), None, [], [], "DETERMINISTIC_ANSWER"),
        (SimpleNamespace(status="graph_answer", prompt="", answer="answer", metadata={}), None,
         [{"schema_name": "shop_answer", "response_text": "structured", "parse_status": "passed", "validation_status": "passed", "route_kind": "primary"}], [],
         "LLM_GENERATED_ANSWER"),
        (SimpleNamespace(status="graph_answer", prompt="", answer="answer", metadata={}), None,
         [{"schema_name": "shop_answer", "response_text": "structured", "parse_status": "passed", "validation_status": "passed", "route_kind": "fallback"}], [],
         "VALIDATED_FALLBACK"),
        (SimpleNamespace(status="graph_answer", prompt="catalog template", answer="catalog template", metadata={}), None,
         [{"schema_name": "turn_plan", "response_text": "plan", "parse_status": "passed", "validation_status": "passed", "route_kind": "primary"}], [],
         "DETERMINISTIC_ANSWER"),
        (SimpleNamespace(status="out_of_scope", prompt="scope reply", answer="scope reply", metadata={}), None,
         [{"schema_name": "turn_plan", "response_text": "plan", "parse_status": "passed", "validation_status": "passed", "route_kind": "primary"}], [],
         "DETERMINISTIC_ANSWER"),
        (SimpleNamespace(status="graph_answer", prompt="answer", answer="answer", metadata={}), None,
         [{"schema_name": "shop_answer", "response_text": "bad json", "parse_status": "failed", "validation_status": "not_reached", "route_kind": "primary"}], [],
         "DETERMINISTIC_ANSWER"),
        (SimpleNamespace(status="product_identity_clarification", prompt="", answer="Which one?", metadata={}), None, [], [], "CLARIFICATION"),
        (None, "BadRequestError", [], [{"status_code": 400}], "PROVIDER_HTTP_400"),
        (None, "RateLimitError", [], [{"status_code": 429}], "PROVIDER_RATE_LIMIT_429"),
        # The graph can catch a 429 and return a safe deterministic answer;
        # the evaluator must still stop the batch after recording that answer.
        (SimpleNamespace(status="graph_answer", prompt="safe fallback", answer="safe fallback", metadata={}), None,
         [], [{"status_code": 429, "error_type": "RateLimitError"}], "PROVIDER_RATE_LIMIT_429"),
        (None, "ProviderCircuitOpen", [], [], "CIRCUIT_OPEN"),
        (None, "OperationalError", [], [], "INFRASTRUCTURE_ERROR"),
    ],
)
def test_pipeline_outcome_taxonomy_is_explicit(result, error_type, model_invocations, attempts, expected):
    assert classify_pipeline_outcome(result, error_type, model_invocations, attempts) == expected


def test_answer_eval_runner_reads_only_the_versioned_synthetic_fixture():
    cases = read_cases(Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl")
    assert len(cases) == 20
    assert {case["dataset"] for case in cases} == {"smh-rag-answer-quality-synthetic-v1"}
    assert all(case["tenant"].startswith("synthetic-") for case in cases)


def test_answer_eval_snapshot_hashes_exact_dataset_bytes_and_embedded_evidence(tmp_path):
    cases_path = Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl"
    cases = read_cases(cases_path)
    snapshot = _dataset_snapshot(cases, cases_path)

    assert snapshot["dataset_sha256"] == hashlib.sha256(cases_path.read_bytes()).hexdigest()
    assert len(snapshot["evidence_snapshot_sha256"]) == 64
    assert snapshot["evidence_manifest"][cases[9]["case_id"]]["policy:available"]
    assert _dataset_snapshot(cases, cases_path)["evidence_snapshot_sha256"] == snapshot["evidence_snapshot_sha256"]


def test_answer_eval_rejects_unmarked_or_non_synthetic_cases():
    with pytest.raises(ValueError, match="approved_synthetic_dataset"):
        validate_cases([{"dataset": "customer-export", "tenant": "shop-1"}])


def test_answer_eval_context_enforces_ephemeral_read_only_sqlite():
    engine = _create_sqlite_engine("sqlite://")
    try:
        with Session(engine) as db:
            db.connection().exec_driver_sql("CREATE TABLE seed (value INTEGER)")
            context = EvaluationContext(
                db=db,
                business_id=90101,
                conversation=object(),
                synthetic=True,
                read_only=True,
            )
            validate_context(context)
            with pytest.raises(OperationalError):
                db.connection().exec_driver_sql("INSERT INTO seed VALUES (1)")
    finally:
        engine.dispose()


def test_synthetic_notification_adapter_captures_intent_without_db_or_external_effects():
    from sqlalchemy import event

    engine = _create_sqlite_engine("sqlite://")
    writes = []
    try:
        with Session(engine) as db:
            db.connection().exec_driver_sql("CREATE TABLE synthetic_probe (id INTEGER)")
            context = EvaluationContext(
                db=db,
                business_id=90111,
                conversation=SimpleNamespace(id=72, business_id=90111),
                synthetic=True,
                read_only=True,
            )
            validate_context(context)

            def capture_sql(_connection, _cursor, statement, _parameters, _context, _many):
                if statement.lstrip().split(None, 1)[0].upper() in {
                    "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "REPLACE"
                }:
                    writes.append(statement)

            event.listen(engine, "before_cursor_execute", capture_sql)
            adapter = SyntheticNotificationAdapter(context)
            persisted = adapter.record(
                db,
                conversation=context.conversation,
                business_id=context.business_id,
                query_text="Cần nhân viên xác nhận điều kiện đổi hàng",
                reason="business_decision_needed",
                idempotency_key="synthetic:notification:1",
            )
            event.remove(engine, "before_cursor_execute", capture_sql)

            assert persisted is False
            assert adapter.intents == [{
                "business_id": 90111,
                "conversation_id": 72,
                "query_text": "Cần nhân viên xác nhận điều kiện đổi hàng",
                "reason": "business_decision_needed",
                "idempotency_key": "synthetic:notification:1",
                "persisted": False,
                "database_write_attempted": False,
                "external_message_attempted": False,
            }]
            assert writes == []
            assert db.connection().exec_driver_sql("PRAGMA query_only").scalar() == 1
    finally:
        engine.dispose()


def test_synthetic_notification_adapter_fails_closed_for_non_synthetic_or_wrong_tenant():
    engine = _create_sqlite_engine("sqlite://")
    try:
        with Session(engine) as db:
            context = EvaluationContext(
                db=db,
                business_id=90112,
                conversation=SimpleNamespace(id=73, business_id=90112),
                synthetic=True,
                read_only=True,
            )
            validate_context(context)
            adapter = SyntheticNotificationAdapter(context)
            with pytest.raises(PermissionError, match="tenant_mismatch"):
                adapter.record(
                    db,
                    conversation=context.conversation,
                    business_id=90113,
                    query_text="synthetic query",
                    reason="business_decision_needed",
                )

            invalid_context = EvaluationContext(
                db=db,
                business_id=90112,
                conversation=context.conversation,
                synthetic=False,
                read_only=True,
            )
            with pytest.raises(PermissionError, match="read_only_synthetic_context"):
                SyntheticNotificationAdapter(invalid_context).record(
                    db,
                    conversation=context.conversation,
                    business_id=context.business_id,
                    query_text="synthetic query",
                    reason="business_decision_needed",
                )
    finally:
        engine.dispose()


def test_answer_evaluation_reports_unexpected_graph_exceptions():
    engine = _create_sqlite_engine("sqlite://")
    try:
        with Session(engine) as db:
            case = read_cases(Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl")[0]
            context = EvaluationContext(
                db=db,
                business_id=90114,
                conversation=SimpleNamespace(id=74, business_id=90114),
                synthetic=True,
                read_only=True,
            )
            validate_context(context)
            result = _evaluate_case(
                case,
                context,
                lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unexpected graph defect")),
                SimpleNamespace(retrieve_shop_knowledge=lambda **_kwargs: []),
                Path("unused-rag-trace.jsonl"),
            )
            assert result["error_type"] == "RuntimeError"
            assert result["pipeline_outcome"] == "INFRASTRUCTURE_ERROR"
            assert result["generated_response"] == ""
            assert result["execution_safety"]["database_query_only"] is True
    finally:
        engine.dispose()


def test_case_011_graph_fallback_is_captured_by_read_only_notification_spy(monkeypatch, tmp_path):
    from app.rag import run_logger
    from app.services.conversation_graph import graph_reply
    from scripts.rag_synthetic_context_factory import synthetic_context
    from unittest.mock import patch

    cases_path = Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl"
    case = next(item for item in read_cases(cases_path) if item["case_id"] == "answer-011-policy-grounded")
    trace_path = tmp_path / "case-011-graph.jsonl"
    monkeypatch.setattr(run_logger, "_log_path", lambda: trace_path)
    context = synthetic_context(case)
    engine = context.db.get_bind()
    try:
        validate_context(context)
        policy = SimpleNamespace(
            content="Sản phẩm đủ điều kiện được yêu cầu đổi trong 7 ngày kể từ khi nhận hàng.",
            document_id=11,
            metadata={"synthetic_evidence_id": "policy:return-v1"},
        )
        bad_draft = json.dumps({
            "answer": "Bạn có thể đổi hàng trong vòng 7 ngày kể từ khi nhận hàng.",
            "sources": [1],
        }, ensure_ascii=False)
        with patch("app.services.conversation_graph.call_llm", side_effect=[
            '{"mode":"answer","tools":["knowledge"]}', bad_draft, bad_draft,
        ]) as model, patch("app.services.quota_service.record_quota_usage"), patch(
            "app.rag.serving.retrieve_shop_knowledge", return_value=[policy]
        ):
            artifact = _evaluate_case(
                case,
                context,
                lambda db, **kwargs: graph_reply(db, **kwargs),
                __import__("app.rag.serving", fromlist=["retrieve_shop_knowledge"]),
                trace_path,
            )

        assert artifact["application_status"] == "graph_answer"
        assert artifact["generated_response"]
        assert "nhân viên kiểm tra" in artifact["generated_response"].lower()
        assert artifact["error_type"] is None
        assert artifact["execution_safety"]["database_query_only"] is True
        assert artifact["side_effects"]["attempted_database_models"] == []
        assert artifact["side_effects"]["flushed_database_models"] == []
        assert artifact["notification_intents"] == [{
            "business_id": context.business_id,
            "conversation_id": context.conversation.id,
            "query_text": "Tôi có thể đổi hàng trong bao lâu?",
            "reason": "business_decision_needed",
            "idempotency_key": "graph-decision:synthetic-eval:answer-011-policy-grounded",
            "persisted": False,
            "database_write_attempted": False,
            "external_message_attempted": False,
        }]
        assert artifact["staff_decision_intents"] == [{
            "reason": "business_decision_needed",
            "conversation_id": context.conversation.id,
        }]
        assert model.call_count == 2
        assert db_query_only(context.db) is True
    finally:
        context.db.close()
        engine.dispose()


def db_query_only(db):
    return bool(db.connection().exec_driver_sql("PRAGMA query_only").scalar())


def test_context_factory_contract_does_not_depend_on_duplicate_module_class_identity():
    engine = _create_sqlite_engine("sqlite://")
    try:
        with Session(engine) as db:
            context = SimpleNamespace(
                db=db,
                business_id=90105,
                conversation=SimpleNamespace(id=1),
                synthetic=True,
                read_only=True,
                platform_db=None,
            )
            validate_context(context)
    finally:
        engine.dispose()


def test_context_factory_contract_rejects_missing_fields():
    with pytest.raises(ValueError, match="context_contract_invalid"):
        validate_context(SimpleNamespace(synthetic=True, read_only=True))


def test_answer_eval_rejects_file_backed_sqlite(tmp_path):
    engine = _create_sqlite_engine(f"sqlite:///{tmp_path / 'synthetic.db'}")
    try:
        with Session(engine) as db:
            context = EvaluationContext(
                db=db,
                business_id=90102,
                conversation=object(),
                synthetic=True,
                read_only=True,
            )
            with pytest.raises(ValueError, match="not_be_file_backed"):
                validate_context(context)
    finally:
        engine.dispose()


def test_provider_gate_refuses_before_importing_context_or_invoking_app(tmp_path):
    cases = read_cases(Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl")[:1]
    calls = []

    def forbidden_factory(_case):
        calls.append("context")
        raise AssertionError("factory should not run without approval")

    with pytest.raises(PermissionError, match="explicit_owner_approval"):
        run_evaluation(cases, forbidden_factory, output_path=tmp_path / "result.json")
    assert calls == []


def test_cli_preflight_reports_not_measured_without_loading_factory(tmp_path, capsys):
    cases_path = Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl"
    assert main(["--cases", str(cases_path), "--output", str(tmp_path / "unused.json")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["answer_quality"] == "NOT_MEASURED"
    assert report["provider_calls"] == 0
    assert "no app/provider/database call" in report["preflight"]


def test_eval_artifact_keeps_quality_unmeasured_when_harness_uses_test_invoker(tmp_path):
    from pathlib import Path
    from types import SimpleNamespace

    case = read_cases(Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl")[0]
    engine = _create_sqlite_engine("sqlite://")
    try:
        with Session(engine) as db:
            context = EvaluationContext(
                db=db,
                business_id=90103,
                conversation=SimpleNamespace(id=1, customer_id=1),
                synthetic=True,
                read_only=True,
            )
            artifact = run_evaluation(
                [case],
                lambda _case: context,
                output_path=tmp_path / "harness-only.json",
                provider_calls_allowed=True,
                invoke_graph=lambda *_args, **_kwargs: SimpleNamespace(
                    status="graph_answer", prompt="test-only output", metadata=None,
                ),
            )
        assert artifact["answer_correctness"].startswith("NOT_MEASURED")
        assert artifact["results"][0]["correctness"].startswith("NOT_MEASURED")
        assert artifact["results"][0]["generated_response"] == "test-only output"
        row = artifact["results"][0]
        assert row["business_id"] == 90103
        assert row["snapshot_sha256"] == artifact["snapshot_sha256"]
        assert len(row["snapshot_sha256"]) == 64
        assert row["snapshot_id"] == artifact["snapshot_id"]
        assert row["question_hash"] == hashlib.sha256(row["question"].encode("utf-8")).hexdigest()
        assert row["model"] == "TEST_INVOKER; no provider model"
        assert row["sampling_config"] == {"invoker": "test-only; no provider request"}
        assert row["answer"] == "test-only output"
        assert row["ranked_source_ids"] == []
        assert row["fallback_used"] is False
        assert row["tokens"] is None
        assert row["llm_calls"] == 0
        assert row["provider_calls_made"] is False
        assert artifact["provider_calls_made"] == 0
        assert artifact["source_snapshot"]
    finally:
        engine.dispose()


def test_provider_rate_limit_stops_batch_and_marks_remaining_cases_unexecuted(tmp_path):
    cases_path = Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl"
    cases = read_cases(cases_path)[:3]
    invoked = []

    def synthetic_factory(case):
        # Import only after run_evaluation has forced the application DB URLs
        # to ephemeral SQLite; model imports otherwise instantiate app engines.
        from scripts.rag_synthetic_context_factory import synthetic_context

        return synthetic_context(case)

    class RateLimitError(Exception):
        pass

    def rate_limited_graph(_db, **kwargs):
        invoked.append(kwargs["job_key"])
        raise RateLimitError("synthetic offline 429 simulation")

    artifact = run_evaluation(
        cases,
        synthetic_factory,
        output_path=tmp_path / "stopped-after-429.json",
        provider_calls_allowed=True,
        invoke_graph=rate_limited_graph,
        dataset_path=cases_path,
    )

    assert invoked == [f"synthetic-eval:{cases[0]['case_id']}"]
    assert artifact["case_count"] == 3
    assert artifact["cases_executed"] == 1
    assert artifact["case_execution_status_counts"] == {"EXECUTED": 1, "NOT_EXECUTED": 2}
    assert artifact["halt_reason"] == "PROVIDER_RATE_LIMIT_429"
    assert artifact["results"][0]["pipeline_outcome"] == "PROVIDER_RATE_LIMIT_429"
    assert [row["pipeline_outcome"] for row in artifact["results"][1:]] == [
        "NOT_EXECUTED_AFTER_PROVIDER_RATE_LIMIT",
        "NOT_EXECUTED_AFTER_PROVIDER_RATE_LIMIT",
    ]
    assert all(row["answer"] is None for row in artifact["results"][1:])
    assert all(not row["provider_calls_made"] for row in artifact["results"][1:])


def test_graph_safe_fallback_with_recorded_429_stops_batch_without_provider_calls(tmp_path):
    cases_path = Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl"
    cases = read_cases(cases_path)[:3]
    invoked = []
    safe_reply = "Mình chưa thể xác minh từ nguồn hiện có."

    def synthetic_factory(case):
        from scripts.rag_synthetic_context_factory import synthetic_context

        return synthetic_context(case)

    def graph_returns_fallback_after_429(_db, **kwargs):
        invoked.append(kwargs["job_key"])
        from app.core.config import settings

        trace_path = Path(settings.RAG_LOG_FILE)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open("a", encoding="utf-8") as trace_file:
            trace_file.write(json.dumps({
                "operation": "conversation_graph",
                "attempt_records": [{"status_code": 429, "error_type": "RateLimitError"}],
                "calls": 1,
            }) + "\n")
        return SimpleNamespace(status="graph_answer", prompt=safe_reply, answer=safe_reply)

    artifact = run_evaluation(
        cases,
        synthetic_factory,
        output_path=tmp_path / "fallback-after-429.json",
        provider_calls_allowed=True,
        invoke_graph=graph_returns_fallback_after_429,
        dataset_path=cases_path,
    )

    assert invoked == [f"synthetic-eval:{cases[0]['case_id']}"]
    assert artifact["results"][0]["answer"] == safe_reply
    assert artifact["results"][0]["pipeline_outcome"] == "PROVIDER_RATE_LIMIT_429"
    assert artifact["cases_executed"] == 1
    assert artifact["case_execution_status_counts"] == {"EXECUTED": 1, "NOT_EXECUTED": 2}
    assert artifact["halt_reason"] == "PROVIDER_RATE_LIMIT_429"
    assert [row["pipeline_outcome"] for row in artifact["results"][1:]] == [
        "NOT_EXECUTED_AFTER_PROVIDER_RATE_LIMIT",
        "NOT_EXECUTED_AFTER_PROVIDER_RATE_LIMIT",
    ]
    assert all(not row["provider_calls_made"] for row in artifact["results"][1:])


def test_eval_refuses_when_sales_journey_is_enabled_before_creating_context(monkeypatch, tmp_path):
    from app.core.config import settings

    cases = read_cases(Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl")[:1]
    calls = []
    monkeypatch.setattr(settings, "SALES_JOURNEY_ENGINE_ENABLED", True)
    with pytest.raises(PermissionError, match="sales_journey_engine_disabled"):
        run_evaluation(
            cases,
            lambda _case: calls.append("context"),
            output_path=tmp_path / "journey-enabled.json",
            provider_calls_allowed=True,
            invoke_graph=lambda *_args, **_kwargs: calls.append("graph"),
        )
    assert calls == []


def test_eval_closes_disposable_session_when_context_validation_fails(monkeypatch, tmp_path):
    cases = read_cases(Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl")[:1]
    engine = _create_sqlite_engine("sqlite://")
    closed = []
    try:
        db = Session(engine)
        original_close = db.close

        def tracked_close():
            closed.append(True)
            original_close()

        monkeypatch.setattr(db, "close", tracked_close)
        context = EvaluationContext(
            db=db,
            business_id=90104,
            conversation=object(),
            synthetic=False,
            read_only=True,
        )
        with pytest.raises(ValueError, match="explicitly_synthetic"):
            run_evaluation(
                cases,
                lambda _case: context,
                output_path=tmp_path / "invalid-context.json",
                provider_calls_allowed=True,
                invoke_graph=lambda *_args, **_kwargs: pytest.fail("graph must not run"),
            )
        assert closed == [True]
    finally:
        engine.dispose()


def test_default_graph_db_guard_rejects_file_backed_or_remote_engine(monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.engine import make_url

    fake_module = SimpleNamespace(engine=SimpleNamespace(
        dialect=SimpleNamespace(name="sqlite"),
        url=make_url("sqlite:///customer-data.db"),
    ))
    monkeypatch.setitem(__import__("sys").modules, "app.database.session", fake_module)
    with pytest.raises(PermissionError, match="not_ephemeral_sqlite"):
        _assert_imported_engines_are_ephemeral()


def test_eval_requires_all_database_settings_to_be_in_memory_sqlite():
    settings = SimpleNamespace(
        DATABASE_URL="sqlite://",
        TENANT_DATABASE_URL="sqlite://",
        PLATFORM_DATABASE_URL="postgresql://example.invalid/production",
    )
    with pytest.raises(PermissionError, match="PLATFORM_DATABASE_URL"):
        _assert_database_settings_are_ephemeral(settings)


def test_image_observation_is_added_only_to_its_synthetic_query():
    cases = read_cases(Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl")
    image_case = next(case for case in cases if case["case_id"] == "answer-019-image-observation")
    normal_case = next(case for case in cases if case["case_id"] == "answer-001-price-stock")
    assert "VISIBLE_IMAGE_OBSERVATION:" in _case_query(image_case)
    assert "VISIBLE_IMAGE_OBSERVATION:" not in _case_query(normal_case)


def test_all_20_synthetic_contexts_are_ephemeral_and_read_only():
    with _ephemeral_database_settings():
        from app.models import Product
        from scripts.rag_synthetic_context_factory import synthetic_context

        cases = read_cases(Path(__file__).parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl")
        assert len(cases) == 20
        for case in cases:
            context = synthetic_context(case)
            try:
                validate_context(context)
                assert context.db.query(Product).count() >= 0
                with pytest.raises(OperationalError):
                    context.db.connection().exec_driver_sql(
                        "CREATE TABLE forbidden_write_probe (id INTEGER)"
                    )
            finally:
                bind = context.db.get_bind()
                context.db.close()
                bind.dispose()


def test_provider_budget_caps_requests_and_reconciles_reported_usage(tmp_path):
    cases = [{"case_id": f"answer-{index:03d}"} for index in range(1, 21)]
    budget = _ProviderBudget(tmp_path / "provider-ledger.json", "baseline", cases)
    try:
        assert budget.ledger["limits"] == {
            "case_executions": 20,
            "physical_attempts": 40,
            "input_tokens": 100_000,
            "output_tokens": 15_000,
        }
        reservation_id, request = budget.reserve_request({
            "model": "openai/gpt-oss-20b",
            "messages": [{"role": "user", "content": "synthetic question"}],
        })
        assert request["max_completion_tokens"] == 512
        budget.settle_success(reservation_id, SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=17, completion_tokens=9),
        ))
        snapshot = budget.snapshot()
        assert snapshot["consumed_total"]["physical_attempts"] == 1
        assert snapshot["consumed_total"]["input_tokens"] == 17
        assert snapshot["consumed_total"]["output_tokens"] == 9
        assert snapshot["reported_total"] == {"input_tokens": 17, "output_tokens": 9}
    finally:
        budget.close()


def test_provider_budget_refuses_unapproved_model_before_request(tmp_path):
    cases = [{"case_id": f"answer-{index:03d}"} for index in range(1, 21)]
    budget = _ProviderBudget(tmp_path / "provider-ledger.json", "baseline", cases)
    try:
        with pytest.raises(PermissionError, match="model_not_approved"):
            budget.reserve_request({
                "model": "another/provider-model",
                "messages": [{"role": "user", "content": "synthetic"}],
            })
        assert budget.ledger["consumed"]["physical_attempts"] == 0
    finally:
        budget.close()


def test_provider_budget_refuses_attempt_and_token_overruns_before_request(tmp_path):
    cases = [{"case_id": f"answer-{index:03d}"} for index in range(1, 21)]
    budget = _ProviderBudget(tmp_path / "provider-ledger.json", "baseline", cases)
    try:
        budget.ledger["consumed"]["physical_attempts"] = 40
        with pytest.raises(EvaluationBudgetExceeded, match="physical_attempts"):
            budget.reserve_request({
                "model": "openai/gpt-oss-20b",
                "messages": [{"role": "user", "content": "synthetic"}],
            })
        budget.ledger["consumed"]["physical_attempts"] = 0
        budget.ledger["consumed"]["input_tokens"] = 100_000 - 1
        with pytest.raises(EvaluationBudgetExceeded, match="input_tokens"):
            budget.reserve_request({
                "model": "openai/gpt-oss-20b",
                "messages": [{"role": "user", "content": "synthetic"}],
            })
        assert budget.ledger["consumed"]["physical_attempts"] == 0
        budget.ledger["consumed"]["input_tokens"] = 0
        budget.ledger["consumed"]["output_tokens"] = 15_000
        with pytest.raises(EvaluationBudgetExceeded, match="output_tokens"):
            budget.reserve_request({
                "model": "openai/gpt-oss-20b",
                "messages": [{"role": "user", "content": "synthetic"}],
            })
        assert budget.ledger["consumed"]["physical_attempts"] == 0
    finally:
        budget.close()


def test_provider_budget_rejects_duplicate_phase_and_excess_case_runs(tmp_path):
    ledger = tmp_path / "provider-ledger.json"
    cases = [{"case_id": f"answer-{index:03d}"} for index in range(1, 21)]
    budget = _ProviderBudget(ledger, "baseline", cases)
    budget.close()
    with pytest.raises(PermissionError, match="phase_already_consumed"):
        _ProviderBudget(ledger, "baseline", cases)
    with pytest.raises(PermissionError, match="post_fix_run_requires_baseline"):
        _ProviderBudget(tmp_path / "new-ledger.json", "post-fix", cases)
