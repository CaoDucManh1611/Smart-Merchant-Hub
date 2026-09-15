# Task 10 — Chuyển tài liệu, RAG, AI usage và cấu hình shop

## Files
- Modify `backend/app/api/documents.py`.
- Modify `backend/app/rag/retriever.py`, `embedder.py`, `llm_caller.py`, `run_logger.py`.
- Modify `backend/app/services/ingestion_service.py`, `meta_config_service.py`.
- Modify `backend/app/models/document.py`, `business_setting.py`.
- Modify `backend/tests/test_rag_tenant_isolation.py`.
- Create `backend/tests/test_tenant_provider_settings.py`.

## Interfaces
- Knowledge documents/chunks/vector indexes and RAG run detail live inside `shop_<id>`.
- Shared LLM pool credentials may remain infrastructure secrets, but shop-specific provider/channel credentials and prompts live encrypted in tenant schema.
- Platform gets aggregated usage/cost counters, never prompt/retrieval text.

## Required work
- Add failing tests for identical document IDs across shops, schema-local vector search, no global `AppSetting` fallback and sanitized platform AI aggregates.
- Move ingestion/retrieval/logging to tenant session and add schema to worker job context rather than query filters.
- Convert `RAG_AUTO_SEED` to provision-time seed per shop; prevent startup from seeding every shop through a global session.
- Remove tenant-sensitive global settings fallback from `meta_config_service.py`; fail closed if a shop credential is absent.
- Run `pytest -q tests/test_rag_tenant_isolation.py tests/test_rag_components.py tests/test_rag_run_logger.py tests/test_tenant_provider_settings.py`.
- Commit `refactor: isolate shop knowledge and AI runtime`.

## Global constraints
Server-generated `shop_<business_id>` schemas only; transaction-local search_path; platform stores only sanitized aggregates, never prompts/retrieval text/tokens; TDD required. Reuse Task 8 tenant-session seam; do not edit Task 5-7 auth/platform-owned files.

