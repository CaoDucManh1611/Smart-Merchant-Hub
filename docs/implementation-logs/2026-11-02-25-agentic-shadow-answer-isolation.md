# Agentic RAG shadow answer isolation — 2026-11-02

## Change

Expanded the auto-reply regression test so it checks the evidence actually passed to `build_prompt`, not only retry flags and log fields.

The test covers five serving cases:

- `off`: no corrective retrieval; original evidence remains in the customer prompt.
- `decision_shadow`: records that retry would run without executing it; original evidence remains in the prompt.
- `execute_shadow`: executes and logs the candidate retrieval, but keeps original evidence in the customer prompt even when the candidate scores higher.
- `active` with a stronger candidate: uses the candidate evidence in the customer prompt.
- `active` with a weaker candidate: rejects it and keeps the original evidence.

All retry modes also verify that the retry preserves the original hard filters, retrieval mode, and disabled PPR setting, and that its timeout stays within the original request's remaining budget.

## Verification

- `backend/tests/test_auto_reply_channels.py -k agentic_rag_modes`: **5 passed**, 57 deselected.
- `backend/tests/test_agentic_rag_controller.py`: **3 passed**.
- `py_compile` passed for the service, controller, and modified test file.
- Tests ran on local Python with `RUN_POSTGRES_TESTS=0`; these targeted tests do not require a database or server.
- Docker Desktop's Linux engine was unavailable, so no container or live-server check was performed.

## Scope and gate

This change adds regression coverage only; it does not change serving defaults, shop settings, prompts, customer traffic, migrations, or model state. Human review of the paired answer set is still pending, so this does not justify enabling the controller for customer replies. No commit or push was made.
