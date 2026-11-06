# Captured offline probe output — 2026-11-05

This file records actual command outcomes from the final verification pass.

## Initial isolated-test invocation (incorrect test mode)

Command omitted RUN_POSTGRES_TESTS=0 and failed while importing conftest before test collection:

    ImportError while loading conftest '...\backend\tests\conftest.py'.
    tests\conftest.py:145: in <module>
        _POSTGRES_TEST_URLS[key] = _prepare_postgres_test_database(value)
    tests\conftest.py:111: in _prepare_postgres_test_database
        raise RuntimeError(
    RuntimeError: Cannot prepare isolated PostgreSQL test database 'crm_chatbot_test' (ConnectionTimeout). Use a PostgreSQL role that can create databases, or create the *_test databases first.

Exit code 1. Zero tests collected/executed. No production database was contacted.

## Correct offline invocation before fixture correction

Command:

    $env:RUN_POSTGRES_TESTS='0'
    python -m pytest tests/test_chatbot_bandit_runtime.py::test_rag_reply_applies_only_bounded_arm_and_saves_decision_trace tests/test_customer_collection_flow.py::CustomerCollectionFlowTests::test_quantity_purchase_followup_uses_last_product_and_waits_for_confirmation -q --tb=short

Result: 1 failed, 1 passed in 6.55s. Bandit failed with StopIteration because its mock query sequence did not model the new workspace-config read. Customer purchase follow-up passed. The bandit fixture was corrected without changing application authorization.

After correction, the complete selected regression including test_chatbot_bandit_runtime.py passed: 450 passed, 1 warning, 6 subtests. See phase1-phase11-regression-20261105-135737.log.
