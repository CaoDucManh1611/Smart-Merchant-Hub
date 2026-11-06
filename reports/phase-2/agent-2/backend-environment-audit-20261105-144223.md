# Smart Merchant Hub backend environment audit

_Read-only environment and test evidence - Agent 2 - 2026-11-05._

## Decision

```text
SUPPORTED_GRAPH_ENVIRONMENT: UNAVAILABLE
PYTHON312_ENVIRONMENT: AVAILABLE FOR NON-GRAPH TESTS
NETWORK INSTALL OR ENVIRONMENT MODIFICATION: NOT PERFORMED
```

The available Python 3.12 environment has the backend test dependencies needed for the non-Graph suites, but it does not have `langgraph`. No package was installed and no environment was changed.

## Interpreter inventory

| Interpreter | Isolation | pytest | langgraph | payos | SQLAlchemy | Pydantic |
|---|---|---:|---:|---:|---:|---:|
| `C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe` | Global Python 3.12.6; `VIRTUAL_ENV=None`; `PYTHONPATH=None` | 9.0.2 | absent | 1.1.0 | 2.0.46 | 2.13.4 |
| Bundled Codex runtime Python | Bundled Python 3.12.14 with `backend\\.migrationdeps;backend` path | present | absent | absent | present | present |

The Python312 executable is the only existing interpreter matching the versions visible in the Agent 1 trace. `langgraph` is absent from both inspected environments. The required dependency reference records `langgraph==1.2.16`.

## Test evidence

| Test scope | Command result | Classification |
|---|---|---|
| Phase 2 engine, policy, integration contract and graph bridge | `52 passed in 1.18s`; exit 0 | PASS |
| Workflow and chatbot routing | `82 passed in 6.29s`; exit 0 | PASS |
| `tests/test_conversation_graph.py` | Collection exit 2: `ModuleNotFoundError: No module named 'langgraph'` | BLOCKED by unavailable dependency |
| Backend compile check | Exit 0 | PASS |

The Graph collection failure is a dependency-environment blocker, not a passing Graph runtime result. The passing Phase 2 bridge tests use the offline test seam and do not establish LangGraph runtime compatibility.

## Safe follow-up

After an isolated integration snapshot is available, provide an approved offline wheelhouse or an already provisioned environment containing the exact supported LangGraph dependency. Then rerun Graph tests and the complete backend regression. Do not install from the network, modify Agent 1's environment, or treat the bundled runtime as production parity.

**ENVIRONMENT AUDIT: GRAPH RUNTIME BLOCKED; NON-GRAPH TEST ENVIRONMENT AVAILABLE.**
