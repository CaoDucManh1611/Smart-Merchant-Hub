# Service and rental RAG case builder

Added `backend/scripts/build_service_rental_rag_cases.py` to produce a local JSONL evaluation draft. It reads tenant catalog entries and their chunk mappings, then includes a positive retrieval case only when the mapped chunk belongs to the same shop, its document is `ready`, and the exact catalog name appears as a complete token sequence in that chunk. Matching ignores case and punctuation but preserves Vietnamese accents.

Run from `backend/`:

```powershell
python scripts/build_service_rental_rag_cases.py --output .local-evaluation/service-rental-cases.jsonl
python scripts/build_service_rental_rag_cases.py --business-id 7 --output .local-evaluation/shop-7-service-rental-cases.jsonl
```

The output is retrieval-only: `expected_chunk_ids` and source references (`catalog_entry_id`, mapping/document/chunk IDs, source hashes, and the exact supporting quote). It contains no generated answer and no inferred industry. Each row uses `label_provenance=agent_generated` and `retrieval_label_status=agent_generated_source_supported`. It is eligible only for exploratory retrieval metrics (`metric_eligible=true`, `metric_eligibility_scope=source_retrieval_only`). Answer scope and answer quality remain pending (`answer_scope_status=pending_human_answer_scope`, `answer_quality_status=pending_human_review`); `human_reviewed=false`. Do not use these labels to score answer correctness. Existing files are protected unless `--overwrite` is supplied. The script performs SELECTs only and does not call external APIs or run migrations.

Rows without a catalog-to-chunk mapping, a ready same-shop document, or an exact name match are omitted. Duplicate identities (same object type and normalized name across catalog IDs) are omitted, including when a duplicate has no mapping. Empty output means no entries met this evidence rule; it does not establish that a shop has no services or rentals. The exact-name rule is a conservative identity check, not a semantic answer-quality judgment; a domain reviewer must still approve scope and expected answer behavior.
