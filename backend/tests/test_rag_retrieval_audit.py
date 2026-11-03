from types import SimpleNamespace

from scripts.audit_rag_retrieval import (
    _audit_chunk_matches_generated_filter,
    paired_cluster_bootstrap_delta,
)


def _catalog_entry(size):
    return SimpleNamespace(
        object_type="product",
        sku_norm=f"SKU-{size}",
        attributes=[SimpleNamespace(key_norm="size", normalized_value=size)],
    )


def test_hard_filter_audit_marks_mixed_product_chunk_as_leakage():
    filters = {"required_attributes": {"size": "L"}}

    assert _audit_chunk_matches_generated_filter([_catalog_entry("L")], "hard_attribute_size", filters)
    assert not _audit_chunk_matches_generated_filter(
        [_catalog_entry("L"), _catalog_entry("M")],
        "hard_attribute_size",
        filters,
    )
    assert not _audit_chunk_matches_generated_filter([], "hard_attribute_size", filters)


def test_paired_cluster_bootstrap_is_seeded_and_reports_cluster_counts():
    rows = [
        {"case_id": "a1", "query_family": "a", "bm25": {"ndcg_at_5": 0.5}, "bm25_mmr": {"ndcg_at_5": 1.0}},
        {"case_id": "a2", "query_family": "a", "bm25": {"ndcg_at_5": 1.0}, "bm25_mmr": {"ndcg_at_5": 0.5}},
        {"case_id": "b1", "query_family": "b", "bm25": {"ndcg_at_5": 0.25}, "bm25_mmr": {"ndcg_at_5": 0.5}},
    ]

    result = paired_cluster_bootstrap_delta(
        rows,
        baseline_key="bm25",
        candidate_key="bm25_mmr",
        metric="ndcg_at_5",
        replicates=200,
        seed=3,
    )
    repeated = paired_cluster_bootstrap_delta(
        rows,
        baseline_key="bm25",
        candidate_key="bm25_mmr",
        metric="ndcg_at_5",
        replicates=200,
        seed=3,
    )

    assert result["case_count"] == 3
    assert result["cluster_count"] == 2
    assert result["mean_delta"] == 0.083333
    assert result["replicates"] == 200
    assert result["seed"] == 3
    assert result["ci_95"] == repeated["ci_95"]
