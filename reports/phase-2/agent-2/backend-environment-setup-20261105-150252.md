# Smart Merchant Hub Graph runtime environment setup instructions

_Instructions only; no environment modification was performed - 2026-11-05 15:02 +07:00._

## Current inventory

| Item | Result |
|---|---|
| Required declaration | `backend/requirements.txt` contains `langgraph==1.2.16` |
| Existing Python312 | `C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe`, Python 3.12.6 |
| Isolation | `sys.prefix == sys.base_prefix`; `VIRTUAL_ENV=None`; no `PYTHONPATH` in the package probe |
| Available packages | pytest 9.0.2, payos 1.1.0, SQLAlchemy, Pydantic |
| Missing package | `langgraph` |
| Graph import | Exit 1 with `ModuleNotFoundError: No module named 'langgraph'` |

## Approved offline setup procedure for a later isolated snapshot

Do not run this procedure in the shared Agent 1 directory. Use a new approved temporary or dedicated environment and an approved local wheelhouse:

```powershell
$graphVenv = 'C:\tmp\smh-graph-venv'
$python312 = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe'

# Preparation command only; execute after workspace ownership and wheelhouse approval.
& $python312 -m venv $graphVenv
& "$graphVenv\Scripts\python.exe" -m pip install --no-index --find-links 'C:\approved\smh-wheelhouse' -r 'C:\path\to\smart-merchant-hub\backend\requirements.txt'
& "$graphVenv\Scripts\python.exe" -c "import importlib.util; assert importlib.util.find_spec('langgraph'); print('langgraph available')"
```

The `pip install` command must use only an approved local wheelhouse. No network install is authorized by this checkpoint. If no wheelhouse exists, the Graph runtime remains blocked.

## Verification sequence

1. Confirm the venv path is separate from the Agent 1 path and record the interpreter path.
2. Verify exact versions for pytest, LangGraph, PayOS, SQLAlchemy and Pydantic.
3. Import `app.services.conversation_graph` before running tests.
4. Run Graph flag-OFF tests, then isolated flag-ON adapter tests with synthetic fixtures.
5. Run the complete backend offline suite and the PostgreSQL-only suite only in an approved PostgreSQL test environment.

**ENVIRONMENT STATUS: NON-GRAPH TESTING AVAILABLE; SUPPORTED GRAPH ENVIRONMENT UNAVAILABLE.**
