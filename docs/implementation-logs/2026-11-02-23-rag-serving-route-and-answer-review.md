# RAG serving route and answer review — 2026-11-02

## Work completed

- Fixed routing precedence in `backend/app/services/auto_reply_service.py`: explicit product price, stock, SKU, and sale-status questions are resolved before the recommendation route. This prevents a product-type word such as “serum” from turning “Serum giá bao nhiêu?” into recommendations for unrelated products.
- Added an explicit sale-status response that distinguishes a product still listed for sale from a listed product that currently has zero available stock.
- Added regression coverage for the serum price route and SKU sale status. The complete `test_chatbot_answer_routing.py` file passes: **43 passed**.
- Updated the local evaluation runner to stop on Groq daily-token-limit errors without long waits, keep deterministic catalog routes, and mark unavailable LLM answers as skipped. The three arms use one frozen retrieval result per case.
- Rebuilt retrieval evidence for the 34 cases and kept the evidence hash stable: `55ff3d44c1611b4fc5c5b3cecee802e44457dabfc499323f709f1e973435212d`.
- Created a 34-row reviewer CSV and a separate deterministic-check report. Every row is still marked `pending`; no machine-generated label was approved.

## Evaluation result

The local snapshot contains 34 cases across shops 1, 4, and 7: 9 price, 9 stock, 3 availability, 3 exact-SKU, 3 unknown-SKU, 3 clarification, 2 policy, and 2 catalog-plus-policy cases.

The deterministic serving path produced answers for 27 catalog-fact cases. Narrow checks against the frozen snapshot passed **27/27**, with no explicit price or stock contradictions. Seven LLM-dependent cases were unavailable. Groq returned HTTP 429 for the configured model `openai/gpt-oss-20b` because the organization reached its daily token limit.

Therefore this is **not** a valid A/B/C quality comparison: A has 0 completed answers; B and C each have only the same 27 deterministic catalog answers; the seven LLM-dependent cases were skipped. The result does not show whether the controller improves answers. Retrieval ran BM25 with PPR disabled.

## Data and validation limits

- The source is the running local Docker tenant database. Some catalog text explicitly labels its stock as test data; these counts are not evidence about live shops.
- Automatic checks cover explicit price/quantity/status/SKU behavior only. They do not judge semantic helpfulness, policy entailment, citation support, or whether the case labels are correct.
- No migration, training, or production traffic was run. No Git commit or push was made.

## Artifacts

- Reviewer instructions: `backend/.local-evaluation/rag-answer-eval-20261102-v2/README-human-review.md`
- Human review CSV: `backend/.local-evaluation/rag-answer-eval-20261102-v2/rag-answer-human-review-v2.csv`
- A/B/C run: `backend/.local-evaluation/rag-answer-eval-20261102-v2/answer-abcs-v3.json`
- Catalog checks: `backend/.local-evaluation/rag-answer-eval-20261102-v2/deterministic-catalog-checks-v2.json`

## Code fingerprints

- `auto_reply_service.py` SHA-256: `CFC18BF6F3582E3022F243727701E670E42929CE56358A51327C555596786E6B`
- `prepare_rag_snapshot_eval.py` SHA-256: `52A7578AB1C1496AEF186DF03643306C82DFC886217F0E22F3AE329A69387E15`

## Next step

Have a human reviewer confirm the 34 expected facts and source references in the CSV. After Groq quota is available (or an authorized evaluation key/model is configured), rerun A/B/C on the same snapshot and cases. Keep customer-facing controller rollout gated until answer correctness, source support, hard-error rate, latency, and cost can be reviewed together.
