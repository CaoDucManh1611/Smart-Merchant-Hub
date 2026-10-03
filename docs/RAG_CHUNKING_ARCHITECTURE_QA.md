# RAG chunking architecture — verification 2026-10-03

Implemented pipeline: Structure-aware → Semantic Chunking → Contextual Embedding → Parent/Neighbor Retrieval.

## Behavior

- Preserve Markdown heading paths and DOCX/HTML headings. Keep table column headers with each row and product/SKU records separate. Quoted multiline CSV cells remain in one product record.
- Split long prose at complete sentence boundaries, protecting decimals and common abbreviations. Never truncate an unsplittable sentence.
- Gemini returns validated indexes into original text units; it cannot replace source wording. Invalid responses, provider errors and quota exhaustion retain local boundaries.
- Embed filename, heading path and SKU with source text. Store citation text separately from the source-derived context prefix.
- Reconstruct parents from stored chunk ranges under the same document and business. Preserve source order and independent search results. Large parents use adjacent evidence.
- Limits: 16 units/8,000 characters per Gemini boundary request, 32 requests/document; parent retrieval at most 16 chunks/6,000 characters, at most 12,000 additional characters per retrieval.

## Verification

68 tests passed across `test_semantic_chunking.py`, `test_rag_components.py`, `test_rag_operations.py`, `test_rag_tenant_isolation.py`, `test_rag_seed_is_tenant_scoped.py`, `test_rag_evaluation.py` and `test_conversation_turn_service.py`.

Live checks:

- Configured `gemini-2.5-flash` and `gemini-2.5-flash-lite` returned HTTP 404. `gemini-3.5-flash-lite`, listed by the account API, successfully returned valid semantic boundaries; configuration was updated accordingly.
- Gemini boundary selection plus contextual embedding succeeded on synthetic policy text: one boundary request, three chunks, 768-dimensional vectors.
- Shop 4, document 2 reindexed from retained source through the existing durable queue: run 4 completed at 100%, 35 chunks, all carrying `structure-semantic-context-v2` metadata and 768-dimensional Gemini vectors.
- Real PostgreSQL retrieval reconstructed a three-chunk parent including the rule, condition and exception. The same query scoped to another business returned no records. The temporary QA document was rolled back and its absence verified.
- `git diff --check` passed; `backend/.env` remains ignored by Git.

## Remaining deployment limitation

Shop 1 retains its old 3072-dimensional vector column and legacy index. Its schema migration was previously blocked by automatic approval review and is not part of this implementation. No schema changes or deletions of original documents/chat history were performed. Legacy chunks remain readable; documents need a source-based reindex to acquire the new chunk metadata and contextual embeddings.

These checks validate implementation and live integration, not a statistical improvement in answer quality across all customer documents. PDF reading order still depends on the source PDF's text extraction quality.
