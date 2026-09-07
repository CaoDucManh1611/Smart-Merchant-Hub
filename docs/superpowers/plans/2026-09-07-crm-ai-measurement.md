# CRM AI measurement and decisioning

## Goal

Turn rule recommendations, supervised ML, A/B testing and contextual bandits into auditable, deterministic CRM capabilities with explicit lifecycle state.

## Implementation tasks

### Rule recommendation

- Add evidence references, source event IDs, proposed workflow version and reviewer fields to suggestions.
- Connect suggestion generation to observed CRM events behind an explicit service call; acceptance creates a versioned workflow draft only, never silently activates it.
- Add review/convert endpoints and audit entries for accept, reject and rollback.

### Supervised ML

- Add model versions, training runs, evaluation metrics and artifact metadata tied to immutable feature snapshots.
- Implement a deterministic dependency-light baseline trainer with holdout metrics and persisted JSON artifact.
- Add versioned inference endpoint; responses include model version, feature snapshot time and confidence/metric metadata.

### A/B testing

- Add exposure events and metric aggregates with idempotency keys, minimum sample size and stop criteria.
- Add report endpoint for per-arm counts, conversion/rate, confidence interval and stopped status; preserve assignment/outcome endpoints.
- Add UI for experiment status, exposure counts and outcome report.

### Contextual bandit

- Add policy configuration/version and arm statistics.
- Implement deterministic epsilon-greedy selection using a stable context hash; update reward statistics idempotently.
- Store policy version, context hash and selection reason on each decision for replay/audit.

## Tests first

- Backend tests for recommendation evidence/approval, deterministic training/evaluation, inference versioning, exposure aggregation, stop criteria, bandit exploration/reward updates and tenant isolation.
- Frontend tests cover review/convert, experiment report and bandit policy states.

## Verification

```powershell
cd backend
$env:PYTHONPATH = "$PWD\.migrationdeps;$PWD"
py -3.12 -m pytest tests/test_rule_recommendation_api.py tests/test_supervised_ml_api.py tests/test_experiment_metrics_api.py tests/test_bandit_policy_api.py -q
```
