# RAG evaluation run — 2026-11-02

## Database and snapshot

- Started Docker Compose PostgreSQL and used host-only overrides for the Compose databases `crm_platform` and `crm_tenant`; no `.env` values were changed or printed.
- Confirmed shops 1, 4, and 7 are active in `crm_platform` and have tenant schemas in `crm_tenant`.
- Read-only migration check found current revisions at the repository heads: legacy `20261020_0061`, platform `20261020_0004_knowledge`, and tenant schemas `20261101_0015`.
- Case validation passed: 25 cases, 36 source references, 23 gold product references, all 25 answer labels still pending.
- Prepared fresh retrieval for all 25 cases with PPR disabled, matching the evaluation configuration.

## Answer comparison

- Ran independent A/B/C generation with Groq `openai/gpt-oss-20b`; no answer reuse and no customer messages sent.
- The provider stopped the run at its organization daily token limit (200,000 TPD; 198,686 used; next request needed 3,634). Result status is `provider_limit` and the comparison remains inconclusive.
- Generated answers: A 5, B 6, C 5; remaining cases were unavailable. Do not interpret the partial latency or hard-error rates as a quality conclusion.
- All labels remain pending. No quality gate or production setting was changed.

## Evaluation-data correction

- The partial run exposed a false positive in the combo case: the answer's three component prices matched the frozen catalog, but the expected facts listed only list/combo/savings totals.
- Created a derivative pending case file with the three snapshot-backed SKU prices and recalculated the saved answers offline. B/C combo price checks now pass; corrected partial hard-error counts are A 0, B 0, C 0. This is a numeric consistency check only, not a human answer-quality judgment.
- Original draft and original enriched pending CSV were preserved.

## Artifacts

- Retrieval: `backend/.local-evaluation/rag-answer-eval-20261102-v2/retrieval-rag-controller-enriched-v1-20261102.json`
- Raw partial A/B/C: `backend/.local-evaluation/rag-answer-eval-20261102-v2/answer-abcs-groq-enriched-v1-20261102.json`
- Offline numeric recheck: `backend/.local-evaluation/rag-answer-eval-20261102-v2/answer-abcs-groq-enriched-v1-20261102-numeric-recheck.json`
- Corrected pending cases: `C:/Users/Administrator/Downloads/rag-controller-testset-v1-enriched-pending-catalog-facts.csv`

## Next step

Wait for Groq quota reset or use an approved provider/quota with the same model and configuration, then generate the missing A/B/C answers. Human review is still required before any answer-quality conclusion or serving change.
