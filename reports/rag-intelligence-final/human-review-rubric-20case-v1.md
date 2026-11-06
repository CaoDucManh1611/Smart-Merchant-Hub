# Human review rubric — synthetic answer quality v1

## Dataset and review state

- Dataset: `backend/test_data/rag_answer_quality_acceptance_v1.jsonl` (20 synthetic cases).
- All labels remain **pending human review**. Automated objective checks are not human approval.
- Cases `answer-016-out-of-stock` and `answer-020-service-read-only-availability` are explicitly disputed and must not be treated as settled gold labels until a reviewer confirms the expected alternative and calendar contract.
- Review each answer against the embedded evidence snapshot and the answerer's actual cited/retrieved evidence. Do not infer facts that are absent from the snapshot.

## Per-answer scoring

Score each dimension from 0 to 2 and record a short evidence-based reason.

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| Correctness | Material factual or action error | Mostly correct with a material omission/minor error | All requested facts and action are correct |
| Groundedness | One or more material claims lack support or cite the wrong tenant/source | Main answer is supported, but a minor claim/source is unclear | Every factual claim is supported by the correct source |
| Completeness | Misses the main request or a required subquestion | Answers the main request but omits a requested detail | Covers all requested parts without padding |
| Sales usefulness | Irrelevant, confusing, or unsafe next step | Understandable but not actionable or unnecessarily long | Natural, concise, relevant; asks one necessary clarification or gives a useful next step |

Also record:

- **Expected action:** answer, clarify, handoff, or read-only lookup. Mark whether actual behavior matches.
- **Unsupported claims:** quote each claim and identify the missing/conflicting evidence. Do not count safe uncertainty language as a factual claim.
- **Hard error (yes/no):** cross-tenant fact; fabricated/current price or stock; unsupported compatibility or policy assurance; ungrounded alternative; or unintended order, payment, booking, or external handoff side effect.
- **Reviewer metadata:** reviewer name/ID, `reviewer_type=human`, timestamp, and notes. Leave all fields blank until a person actually reviews the case.

## Decision rules

1. A safe refusal is not automatically complete or useful. Check whether it names the unresolved detail and gives an appropriate next step.
2. For a partial evidence match, credit supported facts and separately mark omitted questions. Never reward an invented yes/no answer.
3. Product compatibility requires explicit fit evidence. A listed size/specification alone does not prove fit.
4. Current catalog facts must come from the synthetic current-catalog evidence, not stale knowledge text.
5. A read-only availability lookup must not create an appointment. Product advice must not create an order/payment.
6. Keep answer-quality labels separate from execution classifications (`DETERMINISTIC_ANSWER`, `LLM_GENERATED_ANSWER`, `VALIDATED_FALLBACK`, `CLARIFICATION`, and provider/infrastructure errors).
7. Do not use model-generated labels as human labels. If a judge model is later approved, calibrate it against human-scored cases and preserve the two label types separately.

## Disputed gold cases

- `answer-016-out-of-stock`: confirm whether Beta is an acceptable alternative to Alpha from the evidence; if not, revise the expected action/claim before scoring.
- `answer-020-service-read-only-availability`: confirm that the synthetic calendar evidence and the read-only availability tool contract are equivalent; do not accept “slot free” unless the system actually consulted that source, and verify no booking was created.
