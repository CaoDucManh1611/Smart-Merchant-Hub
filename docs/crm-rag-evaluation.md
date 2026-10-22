# CRM/RAG quality evaluation

Run the deterministic CRM evaluation from the repository root:

```powershell
python scripts/evaluate_crm_rag.py
```

The runner loads [`crm-rag-evaluation-set.jsonl`](crm-rag-evaluation-set.jsonl), creates an isolated in-memory SQLite fixture, calls the same CRM answer service used by chat, and writes [`crm-rag-evaluation-report.json`](crm-rag-evaluation-report.json). It uses synthetic records only; it does not call an LLM, embedding service, or external CRM.

The 13 cases cover open-deal counts, stage/date/assignee filters, customer lookup by ID and name, ambiguous names, notes, conversation history, an unknown ID, a cross-tenant ID, a missing customer target, and denied lead access. Expected actions, evidence types, answer terms, citation requirements, and handoff behavior are stored with each case.

The report tracks action accuracy, retrieval recall@k and MRR, answer-contract accuracy, source recall, citation pass rate, handoff precision/recall, latency mean/p50/p95, and estimated AI cost. `answer_accuracy_proxy` is an automatic contract check, not a human semantic judgment. CRM source citations are checked to ensure each marker resolves to a returned record or verified SQL aggregate.

Structured SQL cases have estimated AI cost `0.0` because they do not call a model. Live RAG calls log the configured quota cost estimate in `RagRunLog`; this is a budget estimate, not the provider's final bill. The benchmark latency measures the local SQLite fixture and is not a production latency target. Add reviewed cases to the JSONL file as user queries and CRM schemas evolve.
