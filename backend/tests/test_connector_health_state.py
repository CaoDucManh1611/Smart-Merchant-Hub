import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import connector_pairing as pairing


def test_heartbeat_preserves_reported_error(monkeypatch):
    captured = []
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def read(self): return b'{}'
    monkeypatch.setattr(pairing, "urlopen", lambda request,timeout: Response())
    pairing.report_connector_status("facebook", "http://localhost", "token",state="error",error_code="login_required")
    class Once:
        def __init__(self): self.done=False
        def is_set(self): return self.done
        def wait(self,seconds): self.done=True
    class Immediate:
        def __init__(self,target,**kwargs): self.target=target
        def start(self): self.target()
    original = pairing.report_connector_status
    def record(*args,**kwargs):
        captured.append(kwargs)
        return original(*args,**kwargs)
    monkeypatch.setattr(pairing,"report_connector_status",record)
    monkeypatch.setattr(pairing,"Event",Once)
    monkeypatch.setattr(pairing,"Thread",Immediate)
    monkeypatch.setattr(pairing,"_HEARTBEAT_THREADS",set())
    pairing.start_connector_heartbeat("facebook","http://localhost","token")
    assert captured[0]["state"] == "error"
    assert captured[0]["error_code"] == "login_required"
