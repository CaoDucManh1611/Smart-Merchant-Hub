# RAG answer A/B/C pilot — inconclusive — 2026-11-02

## Outcome

Prepared versioned catalog and knowledge snapshots for shops 1, 4, and 7, selected 34 review cases, and ran the offline A/B/C answer harness against the current Groq model. The run is **inconclusive** and does not pass the quality gate.

The harness used `max_completion_tokens=256`. Sixteen of 85 generated outputs had empty answer text after consuming all 256 completion tokens. Only 18 cases have non-empty answers in all three arms. Groq also returned a 429 tokens-per-day limit and deferred the next attempt by 1,414 seconds. The provider worker was stopped after its checkpoint; no customer channel received any output.

The runner was corrected for the next run: completion cap is now 1,024; it records the model finish reason and empty-answer state; it resumes an answer only when its generation configuration matches, so the old 256-token outputs will be regenerated consistently.

## Immutable input snapshots

Catalog facts and ready knowledge documents were exported from the local PostgreSQL tenant schemas. The catalog snapshot IDs are:

| Shop | Snapshot ID | Products in snapshot | Ready docs / chunks |
| --- | --- | ---: | ---: |
| 1 | `0f83176eda5e4b24d3e99691fe2c67470766c0dc3909c26915f7d9101861faf0` | 6 active | 1 / 5 |
| 4 | `23aabe3b8bc3921432cd0252eb883b7c049ad8e94ef2ca98757db34d7ac4a124` | 1,525 total; 25 active, 1,500 soft-deleted | 1 / 25 |
| 7 | `a67753db4a2ef73c792887b4d968fc3c3cc7839d23fa0c799cc10d416b93d4b` | 25 total; 24 active, 1 archived | 1 / 18 |

Only active catalog products were used to generate ordinary product cases. Three follow-up cases were derived from shop 4's actual compatibility/variant metadata: engine oil needs vehicle type, tires need wheel position and size, and air filters need the exact vehicle model. The set has 11 cases for shop 1, 12 for shop 4, and 11 for shop 7. All 34 remain `pending` human review.

Case types: 9 price, 9 stock, 3 availability, 3 exact SKU, 3 unknown SKU, 3 clarification-required, 2 policy, and 2 catalog-plus-policy. The snapshots contain no promotion-price field, so no sale-price case was invented. Five rows have no suggested document source: two shop 1 product questions whose product is absent from the ready knowledge document, plus the three unknown-SKU probes; those use the catalog snapshot as their fact source.

The ready document files were `rag_test_lunari.txt` (shop 1; no document content hash, so chunk references use content hashes), `linh-kien-xe-may-san-pham.csv` (shop 4), and `linh-kien-xe-may-kho-tri-thuc.txt` (shop 7). Their chunk content hashes/source refs are stored in the snapshot and case JSONL.

## Answer arms and execution

All arms used the configured Groq model `openai/gpt-oss-20b`, temperature 0.1, BM25 retrieval, and PPR disabled:

- **A — no structured snapshot evidence:** current RAG retrieval and prompt, with the structured catalog snapshot omitted. This is a controlled comparison arm, not a replay of a historical binary.
- **B — catalog:** current RAG retrieval plus the case's structured catalog snapshot evidence.
- **C — catalog + controller:** B plus at most one deterministic corrective retrieval when the current evidence is judged weak.

Knowledge retrieval still queried the tenant database during the run; the exported document snapshot is available for review but was not replayed as a frozen retrieval index. Snapshot catalog values were fixed for every case. The harness made no tenant writes or migrations. LLM outputs were not sent to any customer channel.

## Partial results

The checkpoint has 29 started cases out of 34: 28 with all three arms attempted, one partial (`shop7_27_stock`, A only), and five unstarted. The 28 attempted triplets include empty responses, leaving 18 cases with non-empty text in all three arms.

| Arm | Attempts | Empty answers | Non-empty paired numeric flags* | Configured cost estimate for paired outputs* |
| --- | ---: | ---: | ---: | ---: |
| A — no catalog | 29 | 8 | 2 / 18 | $0.098886 |
| B — catalog | 28 | 3 | 2 / 18 | $0.103318 |
| C — catalog + controller | 28 | 5 | 2 / 18 | $0.104322 |

\*Diagnostic only. The paired subset contains 8 shop 1 cases, 9 shop 4 cases, and only 1 shop 7 case. Flags are automatic checks for explicit numeric price/stock claims, not human-verified errors. Wrong-shop is not automatically verifiable from the current evidence metadata. The configured cost rate is $0.002 per 1,000 tokens and is not provider billing. Total recorded usage across the 85 attempts was 256,167 tokens, approximately $0.512334 at that configured rate.

These numbers do **not** establish that catalog or controller improved answer quality. Correctness, citation entailment, helpfulness, unsupported attributes, clarification behavior, and wrong-shop isolation have not been reviewed. The 16 empty answers make the initial model run invalid for a final arm comparison. End-to-end p95 also includes provider rate-limit waiting and is not a normal-service latency measure.

## Required review and rerun

1. Review the 34 cases and answer text in the CSV; keep the human fields pending until a reviewer checks the source, expected response, and each arm.
2. Rerun A/B/C with the updated 1,024-token cap and one consistent generation configuration. The resume logic will rerun old arms that do not match that configuration.
3. Require human review of at least 15–20 cases, including shop 1's catalog/knowledge conflicts, before interpreting quality.
4. Keep the controller out of customer-facing answer mode until wrong price/stock and wrong-shop gates are verifiably clear and answers pass human review.

## Artifacts

- Runner: `backend/scripts/prepare_rag_snapshot_eval.py`.
- Catalog/document snapshot: `backend/.local-evaluation/rag-answer-eval-20261102/shop-catalog-knowledge-snapshots-v1.json`.
- Review suggestions: `backend/.local-evaluation/rag-answer-eval-20261102/rag-answer-review-suggestions-v1.jsonl`.
- Partial raw answers and prompts: `backend/.local-evaluation/rag-answer-eval-20261102/answer-arms-abc-v1.json`.
- Human review sheet: `backend/.local-evaluation/rag-answer-eval-20261102/rag-answer-human-review-v1.csv`.

No commit or push was made. Existing unrelated dirty changes were left untouched.
