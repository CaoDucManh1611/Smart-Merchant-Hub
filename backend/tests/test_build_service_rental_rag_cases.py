from scripts.build_service_rental_rag_cases import (
    _candidate_rows,
    build_cases,
    find_exact_identity_quote,
)


def _row(**overrides):
    row = {
        "catalog_entry_id": 31,
        "entry_business_id": 7,
        "object_type": "service",
        "external_id": "svc-31",
        "catalog_name": "Chăm Sóc Da",
        "catalog_revision": 3,
        "catalog_status": "active",
        "catalog_availability": "available",
        "mapping_id": 501,
        "mapping_catalog_entry_id": 31,
        "mapping_chunk_id": 801,
        "chunk_id": 801,
        "chunk_index": 2,
        "chunk_content": "Dịch vụ Chăm sóc da gồm làm sạch và dưỡng da cơ bản.",
        "document_id": 91,
        "document_business_id": 7,
        "document_filename": "services.md",
        "document_content_hash": "a" * 64,
        "document_status": "ready",
        "embedding_status": "lexical_only",
    }
    row.update(overrides)
    return row


def test_identity_match_is_case_and_punctuation_insensitive_but_accent_sensitive():
    assert find_exact_identity_quote("Chăm Sóc Da", "DỊCH VỤ: chăm sóc da — gói cơ bản") == "chăm sóc da"
    assert find_exact_identity_quote("Chăm Sóc Da", "Dịch vụ chăm sóc dạo") is None
    assert find_exact_identity_quote("Ma", "Dịch vụ Má") is None


def test_builds_pending_source_grounded_cases_for_exact_mapped_ready_identity():
    rows = [
        _row(),
        _row(
            mapping_id=502,
            mapping_chunk_id=802,
            chunk_id=802,
            chunk_index=3,
            chunk_content="Bảng giá: Chăm Sóc Da, thời lượng 60 phút.",
            document_id=92,
            document_filename="price.md",
        ),
    ]

    [case] = build_cases(rows, 7)

    assert case["expected_chunk_ids"] == [801, 802]
    assert case["label_provenance"] == "agent_generated"
    assert case["retrieval_label_status"] == "agent_generated_source_supported"
    assert case["label_status"] == "pending_human_answer_scope"
    assert case["answer_scope_status"] == "pending_human_answer_scope"
    assert case["answer_quality_status"] == "pending_human_review"
    assert case["human_review_status"] == "pending"
    assert case["human_reviewed"] is False
    assert case["metric_eligible"] is True
    assert case["metric_eligibility_scope"] == "source_retrieval_only"
    assert case["answer"] is None
    assert "industry" not in case
    assert all(ref["catalog_entry_id"] == 31 for ref in case["source_refs"])
    assert all(ref["identity_support_quote"] for ref in case["source_refs"])
    assert all(len(ref["chunk_sha256"]) == 64 for ref in case["source_refs"])


def test_omits_unmapped_wrong_shop_nonready_or_unsupported_rows():
    rows = [
        _row(chunk_content="Chỉ có chăm sóc cá nhân, không nêu tên dịch vụ catalog."),
        _row(mapping_id=0),
        _row(entry_business_id=8),
        _row(document_business_id=8),
        _row(document_status="processing"),
        _row(object_type="product"),
        _row(mapping_catalog_entry_id=999),
        _row(mapping_chunk_id=999),
    ]

    assert build_cases(rows, 7) == []


def test_omits_duplicate_offer_identity_even_when_one_duplicate_is_unmapped():
    unmapped_duplicate = _row(
        catalog_entry_id=32,
        external_id="svc-32",
        catalog_name="chăm sóc-da",
        mapping_id=None,
        mapping_catalog_entry_id=None,
        mapping_chunk_id=None,
        chunk_id=None,
        chunk_index=None,
        chunk_content="",
        document_id=None,
        document_business_id=None,
        document_status=None,
    )

    assert build_cases([_row(), unmapped_duplicate], 7) == []


def test_rental_case_keeps_identity_type_and_never_invents_answer():
    row = _row(
        catalog_entry_id=44,
        object_type="rental",
        external_id="rent-44",
        catalog_name="Thuê xe máy",
        mapping_catalog_entry_id=44,
        mapping_chunk_id=804,
        chunk_id=804,
        chunk_content="Dịch vụ Thuê xe máy theo ngày; vui lòng liên hệ để biết điều kiện.",
    )

    [case] = build_cases([row], 7)

    assert case["case_type"] == "rental_identity_retrieval"
    assert case["catalog"]["object_type"] == "rental"
    assert "Thuê xe máy" in case["query"]
    assert case["answer"] is None
    assert case["label_status"] == "pending_human_answer_scope"
    assert case["answer_quality_status"] == "pending_human_review"
    assert case["metric_eligible"] is True
    assert case["metric_eligibility_scope"] == "source_retrieval_only"


def test_database_query_is_same_shop_and_ready_document_scoped():
    class _Result:
        def mappings(self):
            return self

        def all(self):
            return []

    class _ReadOnlyDB:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return _Result()

    from sqlalchemy.dialects import postgresql

    db = _ReadOnlyDB()
    assert _candidate_rows(db, 7) == []
    compiled = db.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "JOIN recommendation_catalog_chunk_mappings" in sql
    assert "JOIN document_chunks" in sql
    assert "JOIN documents" in sql
    assert "recommendation_catalog_entries.business_id =" in sql
    assert "documents.business_id =" in sql
    assert "documents.status =" in sql
    assert "UPDATE " not in sql.upper()
    assert 7 in compiled.params.values()
    assert any(
        isinstance(value, (tuple, list)) and set(value) == {"service", "rental"}
        for value in compiled.params.values()
    )
