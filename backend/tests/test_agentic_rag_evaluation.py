from types import SimpleNamespace

from scripts.evaluate_agentic_rag_pilot import _aggregate, _resolve_expected_chunk_ids


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _ReferenceDB:
    def execute(self, _statement, params):
        assert params["business_id"] == 4
        assert params["source_name"] == "%catalog.csv%"
        return _Rows([
            SimpleNamespace(_mapping={
                "id": 150,
                "content": "SKU | Name | Price | Stock | AO-MAU-XANH | Áo cotton màu xanh | 200000 | 3",
            }),
            SimpleNamespace(_mapping={
                "id": 151,
                "content": "SKU | Name | Price | Stock | AO-MAU-DO | Áo cotton màu đỏ | 200000 | 3",
            }),
        ])


def test_reference_text_remaps_stale_chunk_ids_within_source_file():
    case = {
        "expected_chunk_ids": [99],
        "source_evidence": "catalog.csv",
        "source_chunk_text": "SKU | Name | Price | Stock | AO-MAU-XANH | Áo cotton màu xanh | 200000 | 3",
    }

    ids, status, score = _resolve_expected_chunk_ids(_ReferenceDB(), 4, case)

    assert ids == {150}
    assert status == "mapped_from_source_text"
    assert score == 1.0


def test_aggregate_reports_positive_label_denominator_and_full_arm_latency():
    result = _aggregate([
        {"hit_at_5": 1, "recall_at_5": 1, "mrr": 1, "ndcg_at_5": 1,
         "latency_ms": 110, "scored_positive": True},
        {"latency_ms": 1, "scored_positive": False},
    ])

    assert result["cases"] == 2
    assert result["scored_positive_cases"] == 1
    assert result["ndcg_at_5"] == 1
    assert result["p50_latency_ms"] == 55.5

