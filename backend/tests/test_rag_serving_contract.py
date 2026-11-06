from types import SimpleNamespace
from unittest.mock import Mock
import json

import pytest

from app.rag import serving
from app.rag.agentic_controller import RagRuntimeOptions
from app.rag.claim_verification import render_verified_claims


def test_catalog_price_claim_requires_live_scoped_identity_even_for_alias():
    source = ("CURRENT_CRM_CATALOG:\n"
              "Mã tham chiếu: product:1; Tên: Áo đỏ; SKU: RED-M; Giá hiện hành: 100.000 đồng\n"
              "Mã tham chiếu: product:2; Tên: Áo xanh; SKU: BLUE-L; Giá hiện hành: 200.000 đồng")
    live = {"product:1": {"ref": "product:1", "sku": "RED-M", "name": "Áo đỏ", "price": 100000},
            "product:2": {"ref": "product:2", "sku": "BLUE-L", "name": "Áo xanh", "price": 200000}}
    alias = {"text": "Mẫu này giá 200.000 đồng.", "sources": [1]}
    with pytest.raises(ValueError, match="unbound_catalog_price"):
        render_verified_claims([alias], [source], resolve_offering=live.get)
    with pytest.raises(ValueError, match="claim_product_price_mismatch"):
        render_verified_claims([{**alias, "offering_refs": ["product:1"]}],
                               [source], resolve_offering=live.get)
    valid, _ = render_verified_claims([{**alias, "text": "Mẫu này giá 100.000 đồng.",
                                        "offering_refs": ["product:1"]}],
                                      [source], resolve_offering=live.get)
    assert "100.000 đồng" in valid
    live["product:1"]["price"] = 120000
    with pytest.raises(ValueError, match="stale_catalog_price"):
        render_verified_claims([{**alias, "text": "Mẫu này giá 100.000 đồng.",
                                 "offering_refs": ["product:1"]}],
                               [source], resolve_offering=live.get)
from app.rag.output_contracts import graph_json_completion, ANSWER_SCHEMA


def test_shop_answer_schema_meets_groq_strict_json_schema_requirements():
    schema = ANSWER_SCHEMA.model_json_schema()
    objects = [schema, *schema.get("$defs", {}).values()]
    for node in objects:
        properties = node.get("properties")
        if properties is None:
            continue
        assert set(node.get("required", [])) == set(properties)
        assert node.get("additionalProperties") is False


def options(mode="off"):
    return RagRuntimeOptions("bm25", mode, 2, 0.3, 8.0)


def test_entry_trace_keeps_tenant_for_positional_call(tmp_path, monkeypatch):
    monkeypatch.setattr("app.rag.run_logger.settings.RAG_LOG_FILE", str(tmp_path / "runs.jsonl"))

    @serving.bounded_turn("fixture")
    def reply(db, conversation_id, query_text, business_id):
        return True

    assert reply(object(), 5, "giá sản phẩm", 7) is True
    record = json.loads((tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert record["business_id"] == 7
    assert record["conversation_id"] == 5


def test_shared_contract_keeps_tenant_filters_mode_and_ppr_off(monkeypatch):
    monkeypatch.setattr(serving, "load_rag_runtime_options", lambda db, bid: options())
    retrieve = Mock(return_value=[])
    monkeypatch.setattr("app.rag.retriever.retrieve", retrieve)
    filters = {"sku": ["SKU-RED-M"], "required_attributes": {"size": "M"}}
    trace = {}
    serving.retrieve_shop_knowledge(query="Giá áo?", db=object(), business_id=7,
                                   hard_filters=filters, diagnostics=trace, enable_ppr=True)
    args = retrieve.call_args.kwargs
    assert args["business_id"] == 7 and args["hard_filters"] is filters
    assert args["enable_ppr"] is False and args["retrieval_mode"] == "bm25"
    assert args["timeout_seconds"] <= 8
    assert trace["retrieval_contract"] == "shop_retrieval_v1"


@pytest.mark.parametrize("mode,selected", [("active", True), ("execute_shadow", False)])
def test_adaptive_retry_is_bounded_and_preserves_original_filters(monkeypatch, mode, selected):
    monkeypatch.setattr(serving, "load_rag_runtime_options", lambda db, bid: options(mode))
    chunk = SimpleNamespace(chunk_id=99, similarity=0.9, retrieval_scores={})
    retrieve = Mock(side_effect=[[], [chunk]])
    monkeypatch.setattr("app.rag.retriever.retrieve", retrieve)
    filters = {"sku": ["SKU-RED-M"]}
    trace = {}
    result = serving.retrieve_shop_knowledge(query="giá sản phẩm", db=object(), business_id=7,
                                           hard_filters=filters, diagnostics=trace)
    assert retrieve.call_count == 2
    assert all(call.kwargs["hard_filters"] is filters for call in retrieve.call_args_list)
    assert bool(result) is selected and trace["adaptive_retry_selected"] is selected


def test_retry_budget_expiry_preserves_initial_retrieval(monkeypatch):
    monkeypatch.setattr(serving, "load_rag_runtime_options", lambda db, bid: options("active"))
    retrieve = Mock(return_value=[])
    monkeypatch.setattr("app.rag.retriever.retrieve", retrieve)
    remaining = Mock(side_effect=[8.0, RuntimeError("deadline")])
    monkeypatch.setattr("app.rag.turn_budget.remaining_seconds", remaining)
    trace = {}
    assert serving.retrieve_shop_knowledge(query="giá sản phẩm", db=object(),
                                           business_id=7, diagnostics=trace) == []
    assert retrieve.call_count == 1
    assert trace["adaptive_error_type"] == "RuntimeError"


def test_cross_mode_retry_cannot_replace_initial_result_by_unscaled_similarity(monkeypatch):
    monkeypatch.setattr(serving, "load_rag_runtime_options", lambda db, bid:
                        RagRuntimeOptions("auto", "active", 2, 0.3, 8.0))
    weak = SimpleNamespace(chunk_id=1, similarity=0.1, retrieval_scores={})
    strong = SimpleNamespace(chunk_id=2, similarity=0.9, retrieval_scores={})
    retrieve = Mock(side_effect=[[weak], [strong]])
    monkeypatch.setattr("app.rag.retriever.retrieve", retrieve)
    monkeypatch.setattr("app.rag.retriever._retry_retrieval_mode", lambda mode, trace: "hybrid")
    trace = {}
    result = serving.retrieve_shop_knowledge(query="giá sản phẩm", db=object(),
                                             business_id=7, diagnostics=trace)
    assert result == [weak]
    assert retrieve.call_count == 2
    assert trace["adaptive_retry_selected"] is False


def test_claim_cannot_borrow_another_products_price_from_same_source():
    source = "Tên: Áo đỏ; Giá hiện hành: 100.000 đồng\nTên: Áo xanh; Giá hiện hành: 200.000 đồng"
    with pytest.raises(ValueError, match="price_mismatch"):
        render_verified_claims([{"text": "Áo đỏ giá 200.000 đồng.", "sources": [1]}], [source])
    answer, manifest = render_verified_claims([
        {"text": "Áo đỏ giá 100.000 đồng.", "sources": [1]},
    ], [source])
    assert "[Source 1]" in answer and manifest == [{"claim_index": 1, "source_ids": [1]}]


def test_two_product_comparison_binds_each_price_to_its_catalog_row():
    source = "Tên: Áo đỏ; Giá hiện hành: 100.000 đồng\nTên: Áo xanh; Giá hiện hành: 200.000 đồng"
    valid = [{"text": "Áo đỏ giá 100.000 đồng, Áo xanh giá 200.000 đồng.", "sources": [1]}]
    answer, _ = render_verified_claims(valid, [source])
    assert "Áo xanh giá 200.000" in answer
    with pytest.raises(ValueError, match="price_mismatch"):
        render_verified_claims([{"text": "Áo đỏ giá 200.000 đồng, Áo xanh giá 100.000 đồng.",
                                "sources": [1]}], [source])


def test_claim_must_reference_its_actual_supporting_source():
    sources = ["Giá 100.000 đồng.", "Đổi trả trong 7 ngày."]
    with pytest.raises(ValueError, match="unsupported_claim"):
        render_verified_claims([{"text": "Giá 100.000 đồng.", "sources": [2]}], sources)


def test_native_structured_answer_is_rendered_once_from_claims(monkeypatch):
    native = Mock(return_value={"claims": [{"text": "Thông tin đã xác nhận.", "sources": [1]}],
                               "calculation": None, "needs_staff_decision": False})
    monkeypatch.setattr("app.rag.llm_caller.call_structured", native)
    model = Mock()
    result = graph_json_completion([], schema=ANSWER_SCHEMA, name="answer", model=model, default_model=model)
    assert "Thông tin đã xác nhận" in result
    native.assert_called_once()
    model.assert_not_called()
