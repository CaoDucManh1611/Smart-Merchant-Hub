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

## 80-case evaluation set

The versioned set is `docs/chatbot-evaluation-set.jsonl`. It contains 80 cases
covering products, orders, delivery, returns, payment, recommendations,
handoff, clarification, noisy language, and safety/tenant isolation.

Export one JSON object per prediction with these fields:

```json
{"id":"product_001","action":"lookup_product","retrieved_contents":["Serum01 ..."],"answer":"..."}
```

Run the provider-neutral gate from `backend`:

```bash
python scripts/evaluate_rag.py predictions.jsonl --top-k 5 --min-action-accuracy 0.8 --min-recall 0.8
```

The command reports action accuracy, Recall@K, mean reciprocal rank, and the
rate of answers that avoid explicitly forbidden unsupported claims. It exits
non-zero when either configured promotion threshold is missed.
