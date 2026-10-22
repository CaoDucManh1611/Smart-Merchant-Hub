# AI RAG learning operations

## Knowledge ingestion

`POST /api/documents/upload` validates and stores the source file, creates a
`rag_runs` row, and queues a durable `rag.ingest` job in one tenant
transaction. Chunking and embedding run only in the CRM worker. The Knowledge
Base screen polls `GET /api/documents/{document_id}/runs` and displays the
persisted `load`, `chunk`, `embed`, `store`, and `complete` progress.

Failed queue jobs use bounded exponential backoff. Provider errors are
sanitized before storage. An operator can retry a terminal failed run through
`POST /api/documents/runs/{run_id}/retry`; a second active run for the same
document is rejected to prevent duplicate embeddings.

## Hybrid retrieval and tenant boundary

Every lexical and pgvector query joins `document_chunks` to `documents` and
requires both `documents.status = 'ready'` and
`documents.business_id = :business_id`. The explicit business predicate is
kept even in a schema-bound tenant session as defense in depth. If vector
embedding/search is unavailable, retrieval falls back to keyword results for
that same business only.

Successful query embeddings are cached in-process for up to 512 entries keyed
by provider, model, dimension and text; returned lists are independent copies.
Failures are never cached. Query embeddings contain no retrieved tenant facts,
and document/order lookup still enforces the business predicate on every call.
Serving run logs record `retrieval_mode`, `retrieval_fallback_stage` and
`retrieval_error_type` directly. This makes provider degradation visible for
both internal chat and every channel routed through `process_rag_auto_reply`.

## AI provider stability and safe fallback

LLM and embedding requests try at most three distinct keys per provider call.
Rate-limit, quota, authentication, connection, and timeout failures cool down
the affected key; a provider-specific circuit breaker stops repeated calls
when failures continue. Each provider is capped at four in-flight requests per
backend worker, with a bounded wait. These limits are process-local, so a
deployment with multiple workers has one such cap per worker.

Retries happen only around model/embedding calls. A model retry cannot send a
customer message because outbound delivery starts only after a final answer is
accepted. Streaming retries stop as soon as any text has been emitted. Channel
sends keep their existing idempotency key; an ambiguous delivery is marked
`delivery_unknown` and is not automatically sent again. If the model remains
unavailable, the app returns one safe fallback and marks the conversation for
staff review instead of inventing an answer.

## 100-case isolated evaluation

The versioned set is `docs/chatbot-evaluation-set.jsonl`. It contains 100 cases
covering products, orders, delivery, returns, payment, recommendations,
handoff, clarification, noisy language, and safety/tenant isolation.

The case runner always evaluates each prompt as a fresh turn with no prior
conversation history. First run the no-provider route check:

```powershell
python scripts/evaluate_chatbot_100.py
```

To score a provider-backed or fixture-backed run, export one JSON object per
case ID to JSONL. Do not put previous cases into `conversation_history`:

```json
{"id":"product_001","action":"lookup_product","retrieved_contents":["Serum01 ..."],"retrieved_sources":["crm_product"],"answer":"...","handoff_required":false,"latency_ms":182,"provider_error":null}
```

Score the responses and write the complete per-case diagnostics:

```bash
python scripts/evaluate_chatbot_100.py --predictions predictions.jsonl --output docs/chatbot-evaluation-100-latest-report.json
```

The report separates route accuracy, retrieval recall/MRR (only for knowledge
retrieval cases), expected source coverage, required/forbidden answer terms,
citation validity, handoff precision/recall, provider errors, and mean/p50/p95
latency. The `cases` list shows missing evidence and failed checks by ID. These
automatic checks are screening signals, not a semantic quality score; review
the answer and cited passages for each failed or high-risk case.

For quick regression, `python scripts/evaluate_rag_set.py` checks the same 100
routes only. `python scripts/evaluate_rag_quality.py` separately measures the
40 synthetic demo RAG queries using a local fixture and lexical fallback; it
does not call a provider. Neither command scores generated answers. A provider-
backed run can consume configured API quota, so inspect the fixture and cost
before running it.

When a case fails, diagnose in this order: wrong action means routing; correct
action but absent/wrong CRM source means data selection or tenant scope; correct
source but bad answer/citation means prompt or answer validation; a provider
error means key/quota/service availability. Change retrieval only for cases
whose expected knowledge source is missing or ranked too low, then rerun the
same IDs and the full regression set. Prices, stock, customer orders, and sales
aggregates must come from tenant CRM records; stable policies/how-to come from
approved knowledge documents. RFM is calculated by the CRM analytics service
from completed/paid-delivered orders, net of refunds—not from RAG documents.

The imported `Data_RAG` checkpoints have an untouched 10,000-conversation test
split. Reinstall them after a new training run and rerun portable inference from
the repository root:

```powershell
python scripts/install_data_rag_models.py --training-run "C:\path\to\training_runs\run_..."
python scripts/evaluate_data_rag_integration.py --dataset "C:\path\to\Data_RAG\dataset" --training-run "C:\path\to\training_runs\run_..."
```

`evaluate_live_rag_demo.py` is the provider-backed check. It embeds the four
synthetic demo files in a temporary PostgreSQL schema, calls the app retriever
and answer model on the 40 synthetic RAG cases, then rolls the schema back. It
embeds the questions in a batch with `RETRIEVAL_QUERY`, validates all vectors,
and passes them into the same serving retriever, avoiding 40 separate provider
requests. Batch failure aborts the run instead of producing a mixed-mode score. It
drops the newly created HNSW index in that tiny schema so exact vector search
is repeatable and does not depend on a freshly randomized approximate-index
graph. The real application index is not changed. It does not access a shop
schema or a messaging platform. It can consume configured embedding/model
quota. Its report stores only synthetic queries and answers. A separate
production-like HNSW check is still needed before release.

For the supplied demo pack, stage only the four demo sources and the JSONL
cases into the already-running backend container, then run with the strict
vector gate. If the command exits with code 2, open the report anyway: it has
the case IDs that silently fell back, but the run is not valid for promotion.

```powershell
docker exec crm_chatbot_backend mkdir -p /tmp/data-rag-eval-pack
$files = @(
  "demo-store-profile.vi-en.md",
  "demo-products.vi-en.csv",
  "demo-support-policies.vi-en.md",
  "demo-industry-playbook.vi-en.md",
  "demo-rag-evaluation.vi-en.jsonl"
)
foreach ($file in $files) {
  docker cp (Join-Path "knowledge_base" $file) "crm_chatbot_backend:/tmp/data-rag-eval-pack/$file"
}
docker exec crm_chatbot_backend python /app/root-scripts/evaluate_live_rag_demo.py `
  --source-dir /tmp/data-rag-eval-pack `
  --cases /tmp/data-rag-eval-pack/demo-rag-evaluation.vi-en.jsonl `
  --output /tmp/data-rag-eval-pack/live-report.json `
  --require-full-vector
docker cp crm_chatbot_backend:/tmp/data-rag-eval-pack/live-report.json docs/data-rag-live-report.json
```

The evaluator records per-case vector/pgvector fallbacks, requires zero such
fallbacks for promotion, and uses an exact sequential vector scan in the small
temporary schema. It does not change the application's real HNSW index.

For a local code-only refresh when unrelated database migrations are pending,
the checked-in override starts the backend directly and refreshes the worker:

```powershell
docker compose -f docker-compose.yml -f scripts/docker-rag-runtime.override.yml up -d --no-deps --no-build backend worker
```

This override intentionally skips migration commands. Run the project's
normal migration/deployment procedure separately when releasing schema changes.
