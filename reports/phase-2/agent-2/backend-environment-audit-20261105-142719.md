# Smart Merchant Hub Phase 2.4 backend environment audit

## Repository requirements

`backend/requirements.txt` requires:

- `pytest==9.0.2`
- `sqlalchemy==2.0.46`
- `pydantic-settings==2.11.0`
- `payos==1.1.0`
- `langgraph==1.2.16`
- the remaining FastAPI, database, RAG and provider packages.

## Interpreters inspected

| Candidate | Result |
|---|---|
| `python`, `python3`, `pytest` on PATH | Not found |
| `py -0p` | No installed Pythons found |
| `pyvenv.cfg` under `C:\Users\Administrator` | None found |
| Bundled interpreter | `C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`, Python 3.12.14 |
| Offline package snapshot | `backend\.migrationdeps` |

The bundled interpreter with `PYTHONPATH` set to `backend\.migrationdeps;backend` provides pytest, SQLAlchemy and Pydantic. It does not provide `langgraph` or `payos`. The bundled interpreter without that package path also lacks pytest and SQLAlchemy.

## Commands and probes

```powershell
$env:PYTHONPATH = "<workspace>\backend\.migrationdeps;<workspace>\backend"
$env:RUN_POSTGRES_TESTS = "0"
& "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -c "import importlib.util; ..."
```

Probe result:

```text
pytest=True
langgraph=False
payos=False
sqlalchemy=True
pydantic=True
```

No package installation or network access was attempted. No Agent 1 environment was found or modified.

## Runtime blocker

The Graph imports `langgraph.graph` at module import time. The workflow/chatbot import chain reaches `payos` before collection. Consequently:

- Graph runtime tests are `BLOCKED`, not PASS.
- Workflow/chatbot runtime tests are `BLOCKED`, not PASS.
- No stub module was introduced and no mocked import is used to claim runtime verification.

## Isolated setup guidance for the integration owner

Create a separate backend test environment after Agent 1 supplies an approved interpreter or offline wheelhouse. Install only from that approved local source, with versions constrained by `backend/requirements.txt`; do not reuse or mutate the Agent 1 environment. Verify `pytest`, `langgraph==1.2.16`, `payos==1.1.0`, SQLAlchemy and Pydantic before running Graph tests. Keep `RUN_POSTGRES_TESTS=0` for the local synthetic run and use a separately approved disposable database for any SQL round trip.

This is setup guidance only. No environment was created and no dependency was installed in Phase 2.4.
