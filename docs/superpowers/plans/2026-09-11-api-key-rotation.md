# API Key Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe round-robin rotation and cooldown handling for up to five LLM/embedding API keys.

**Architecture:** A provider-agnostic `ApiKeyPool` owns selection and cooldown state. LLM and embedding callers request a key per attempt and report failures without exposing raw values. Existing single-key settings remain backward compatible.

**Tech Stack:** FastAPI/Python, Pydantic Settings, OpenAI-compatible clients, Google Generative AI, unittest/pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-crm-completion-followups-design.md`

## Global Constraints

- Raw key values never enter logs, HTTP responses, audit metadata, or tests' failure messages.
- `LLM_API_KEY`, `GROQ_API_KEY`, and `EMBEDDING_API_KEY` remain valid single-key fallbacks.
- Rotation is process-local and does not claim distributed quota coordination.
- A key is cooled down only for authentication, rate-limit, or transient provider errors.

---

### Task 1: Add the key pool service

**Files:**
- Create: `backend/app/services/api_key_pool.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_api_key_pool.py`

**Interfaces:**
- `ApiKeyPool(keys: list[str], cooldown_seconds: int = 60)`
- `ApiKeyPool.next_key() -> str`
- `ApiKeyPool.report_failure(key: str, error: Exception) -> None`
- `ApiKeyPool.snapshot() -> dict`
- `settings.llm_api_keys`, `settings.embedding_api_keys`, and `settings.groq_api_keys` return parsed lists.

- [ ] **Step 1: Write failing tests** covering five-key round-robin, empty pools, cooldown skip, recovery after cooldown, and redacted snapshots.
- [ ] **Step 2: Run `pytest tests/test_api_key_pool.py -q` and confirm import/attribute failures.**
- [ ] **Step 3: Implement the pool with a monotonic clock, a lock, and an error classifier that recognizes 401/403/429/5xx and quota markers.**
- [ ] **Step 4: Add comma-separated settings fields and preserve legacy fallbacks.**
- [ ] **Step 5: Run the focused tests and confirm all pass.**

### Task 2: Integrate LLM and embedding callers

**Files:**
- Modify: `backend/app/rag/llm_caller.py`
- Modify: `backend/app/rag/embedder.py`
- Modify: `backend/app/rag/run_logger.py` if provider metadata is logged
- Test: `backend/tests/test_llm_key_rotation.py`

**Interfaces:**
- Provider callers use `get_llm_key(provider)` and `get_embedding_key(provider)` helpers backed by the pools.
- A provider failure calls `report_failure` and retries at most once with a different key.

- [ ] **Step 1: Write failing monkeypatch tests proving a first 429 uses the next key and successful calls stop retrying.**
- [ ] **Step 2: Run the tests and confirm callers still use only the legacy single key.**
- [ ] **Step 3: Replace direct key reads with pool selection for Gemini, OpenAI, Groq, and embeddings; keep local embeddings key-free.**
- [ ] **Step 4: Ensure log messages contain provider/model/key index only, never the key or a full exception containing credentials.**
- [ ] **Step 5: Run focused RAG tests plus the existing chatbot runtime tests.**

### Task 3: Document configuration and verify

**Files:**
- Modify: `backend/.env.example`
- Modify: `README.md`
- Test: `backend/tests/test_production_config.py`

- [ ] **Step 1: Add `LLM_API_KEYS`, `GROQ_API_KEYS`, and `EMBEDDING_API_KEYS` examples with five comma-separated placeholders.**
- [ ] **Step 2: Add production validation that at least one usable key exists for the configured provider.**
- [ ] **Step 3: Run the config test, full backend suite, and `git diff --check`.**
