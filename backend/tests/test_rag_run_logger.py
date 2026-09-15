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


def test_rag_run_log_does_not_persist_customer_query(tmp_path, monkeypatch):
    log_path = tmp_path / "rag_runs.jsonl"
    monkeypatch.setattr("app.rag.run_logger.settings.RAG_LOG_FILE", str(log_path))

    query = "Địa chỉ giao hàng của Nguyễn Văn A là 0912345678"
    with RagRunLog("chat", query_preview=query):
        pass

    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert "query_preview" not in record
    assert query not in log_path.read_text(encoding="utf-8")
    assert record["query_chars"] == len(query)
    assert len(record["query_hash"]) == 16


def test_rag_run_log_redacts_identifiers_in_errors(tmp_path, monkeypatch):
    log_path = tmp_path / "rag_runs.jsonl"
    monkeypatch.setattr("app.rag.run_logger.settings.RAG_LOG_FILE", str(log_path))

    with RagRunLog("chat") as run:
        run.finish(
            "error",
            error="SMTP failed for thienshinn47@gmail.com phone 0912345678 token=secret",
        )

    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert "thienshinn47@gmail.com" not in record["error"]
    assert "0912345678" not in record["error"]
    assert "secret" not in record["error"]
