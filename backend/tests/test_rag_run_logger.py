import json

from app.rag.run_logger import RagRunLog


def test_rag_run_log_writes_one_record(tmp_path, monkeypatch):
    log_path = tmp_path / "rag_runs.jsonl"
    monkeypatch.setattr("app.rag.run_logger.settings.RAG_LOG_FILE", str(log_path))

    with RagRunLog("chat", query_preview="Xin giá", top_k=5) as run:
        run.update(phase="retrieve", chunks_found=2)
        run.finish("success", phase="complete", answer_chars=24)

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["run_id"] == run.run_id
    assert records[0]["operation"] == "chat"
    assert records[0]["status"] == "success"
    assert records[0]["chunks_found"] == 2
    assert records[0]["duration_ms"] >= 0


def test_rag_run_log_records_exception(tmp_path, monkeypatch):
    log_path = tmp_path / "rag_runs.jsonl"
    monkeypatch.setattr("app.rag.run_logger.settings.RAG_LOG_FILE", str(log_path))

    try:
        with RagRunLog("chat_stream"):
            raise RuntimeError("embedding unavailable")
    except RuntimeError:
        pass

    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["status"] == "error"
    assert record["error_type"] == "RuntimeError"
    assert record["error"] == "embedding unavailable"
