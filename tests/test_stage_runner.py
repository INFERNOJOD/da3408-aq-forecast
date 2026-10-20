import json

import pytest
from src.common import stage_runner
from src.common.errors import DataValidationError, PipelineStageError


def params(tmp_path):
    return {"paths": {"reports_dir": str(tmp_path)}, "cutoff": "c"}


def test_rows_per_second():
    assert stage_runner.rows_per_second(1000, 2.0) == 500.0
    assert stage_runner.rows_per_second(None, 2.0) is None
    assert stage_runner.rows_per_second(10, 0) is None


def test_success_writes_files(tmp_path, monkeypatch):
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    rec = stage_runner.run_stage("x", lambda: {"rows_out": 10}, params(tmp_path), "r1")
    assert rec["status"] == "success" and rec["run_id"] == "r1"
    assert (tmp_path / "stage_metrics" / "x.json").exists()
    line = json.loads((tmp_path / "runs.jsonl").read_text().splitlines()[0])
    assert line["stage"] == "x" and line["rows_out"] == 10


@pytest.mark.parametrize(
    "exc, text",
    [
        (DataValidationError("bad data"), "bad data"),
        (ValueError("oops"), "ValueError: oops"),
        (PipelineStageError("x", "inner"), "inner"),
    ],
)
def test_failure_is_recorded_and_wrapped(tmp_path, monkeypatch, exc, text):
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)

    def boom():
        raise exc

    with pytest.raises(PipelineStageError):
        stage_runner.run_stage("x", boom, params(tmp_path), "r2")
    line = json.loads((tmp_path / "runs.jsonl").read_text().splitlines()[0])
    assert line["status"] == "failed" and text in line["error"]


def test_push_failure_is_swallowed(tmp_path):
    rec = {
        "stage": "x",
        "run_id": "r",
        "status": "success",
        "duration_s": 1.0,
        "rows_per_sec": 5.0,
    }
    assert stage_runner.push_metrics(rec, "http://127.0.0.1:1") is False


def test_git_commit_returns_string():
    assert isinstance(stage_runner.current_git_commit(), str)


def test_run_id_env(monkeypatch):
    monkeypatch.setenv("PIPELINE_RUN_ID", "abc")
    assert stage_runner.new_run_id() == "abc"
    monkeypatch.delenv("PIPELINE_RUN_ID")
    assert len(stage_runner.new_run_id()) == 15
