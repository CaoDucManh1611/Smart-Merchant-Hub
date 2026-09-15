from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_crm_worker_runs_channel_health_on_a_bounded_interval():
    source = (ROOT / "app" / "scripts" / "crm_job_worker.py").read_text(encoding="utf-8")
    assert "run_scheduled_channel_health" in source
    assert "CHANNEL_HEALTH_INTERVAL_SECONDS" in source
    assert "time.monotonic()" in source
    assert "Channel health cycle failed" in source
