"""Tests for the ops runner, with a fake pipeline, registry and smoke check."""

import json
from datetime import datetime

import pytest
from src.backend.model_client import ModelUnavailableError
from src.common.errors import RegistryError
from src.ops import runner as ops

PARAMS = (
    'cities: [Delhi]\n\ncutoff: "2020-03-24 23:00:00"   # last hour used for training\n'
)
END = "2020-06-30 23:00:00"


class FakeRegistry:
    def __init__(self, fail=False):
        self.rolled = 0
        self.fail = fail

    def rollback(self, version=None):
        if self.fail:
            raise RegistryError("registry down")
        self.rolled += 1
        return "2", "1"


class FakePipeline:
    """Records the call and writes the reports a real run would write."""

    def __init__(self, reports, code=0, promoted=True, stage_error=None):
        self.reports, self.code, self.promoted = reports, code, promoted
        self.stage_error = stage_error
        self.calls = []
        self.trigger_seen = None

    def __call__(self, env, log_path):
        self.calls.append(env)
        trigger = self.reports / "drift_trigger.json"
        self.trigger_seen = (
            json.loads(trigger.read_text()) if trigger.exists() else None
        )
        cutoff = ops.read_cutoff(self.reports.parent / "params.yaml")
        if self.stage_error:
            rec = {"run_id": env["PIPELINE_RUN_ID"], "stage": "features",
                   "status": "failed", "error": self.stage_error}  # fmt: skip
            (self.reports / "runs.jsonl").write_text(json.dumps(rec) + "\n")
        (self.reports / "register.json").write_text(
            json.dumps(
                {
                    "promoted": self.promoted,
                    "version": "2" if self.promoted else None,
                    "mlflow_run_id": "abc",
                    "reasons": [] if self.promoted else ["mean MAE not lower"],
                    "cutoff": cutoff,
                }
            )
        )
        return self.code


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "params.yaml").write_text(PARAMS)
    reports = tmp_path / "reports"
    reports.mkdir()
    (tmp_path / "ops" / "requests").mkdir(parents=True)

    def make(pipeline=None, smoke=(True, "ok"), registry=None, free=8000):
        pipeline = pipeline or FakePipeline(reports)
        registry = registry or FakeRegistry()
        runner = ops.OpsRunner(
            ops_dir=tmp_path / "ops",
            params_path=tmp_path / "params.yaml",
            reports_dir=reports,
            replay_end=END,
            registry=registry,
            smoke=lambda version: smoke,
            run_pipeline=pipeline,
            free_mb=lambda: free,
            now=lambda: datetime(2026, 10, 20, 12, 0, 0),
        )
        return runner, pipeline, registry

    return tmp_path, make


def request(
    tmp_path, rid="rt-1", status="queued", cutoff="2020-04-02T05:00:00", **more
):
    rec = {"request_id": rid, "reason": "drift_alert:PM25DriftHigh", "cutoff": cutoff,
           "created_at": "2026-10-20T11:59:00", "status": status, **more}  # fmt: skip
    path = tmp_path / "ops" / "requests" / f"{rid}.json"
    path.write_text(json.dumps(rec))
    return path


def test_cutoff_line_is_replaced_and_comment_kept(tmp_path):
    path = tmp_path / "params.yaml"
    path.write_text(PARAMS)
    assert ops.read_cutoff(path) == "2020-03-24 23:00:00"
    ops.write_cutoff(path, "2020-04-02 05:00:00")
    text = path.read_text()
    assert 'cutoff: "2020-04-02 05:00:00"   # last hour used for training' in text
    assert text.startswith("cities: [Delhi]")


@pytest.mark.parametrize(
    "requested, error",
    [
        ("2020-03-24T23:00:00", "not after the current cutoff"),
        ("2020-07-01T00:00:00", "after the replay end"),
        ("soon", "Bad cutoff"),
        (None, "Bad cutoff"),
    ],
)
def test_new_cutoff_rejects_bad_values(requested, error):
    with pytest.raises(ops.RequestError, match=error):
        ops.new_cutoff(requested, "2020-03-24 23:00:00", END)


def test_new_cutoff_rounds_to_the_hour():
    assert ops.new_cutoff("2020-04-02T05:30:10", "2020-03-24 23:00:00", END) == (
        "2020-04-02 05:00:00"
    )


def test_promoted_candidate_passes_smoke(setup):
    tmp_path, make = setup
    runner, pipeline, registry = make()
    path = request(tmp_path, trigger="drift_alert", drift={"cities_exceeding": 4})
    assert runner.run_once() == 1
    rec = json.loads(path.read_text())
    assert rec["status"] == "done" and rec["promoted"] is True and rec["version"] == "2"
    assert rec["cutoff"] == "2020-04-02 05:00:00" and rec["smoke"] == "ok"
    assert pipeline.calls[0] == {
        "PIPELINE_TRIGGER": "drift_alert", "PIPELINE_RUN_ID": "20261020-120000",
    }  # fmt: skip
    assert pipeline.trigger_seen == {"cities_exceeding": 4}
    assert not (tmp_path / "reports" / "drift_trigger.json").exists()
    assert ops.read_cutoff(tmp_path / "params.yaml") == "2020-04-02 05:00:00"
    assert registry.rolled == 0 and runner.pending() == []


def test_rejected_candidate_is_done_with_reasons(setup):
    tmp_path, make = setup
    runner, _, _ = make(pipeline=FakePipeline(tmp_path / "reports", promoted=False))
    path = request(tmp_path)
    runner.run_once()
    rec = json.loads(path.read_text())
    assert rec["status"] == "done" and rec["promoted"] is False
    assert rec["reasons"] == ["mean MAE not lower"] and "smoke" not in rec


def test_failed_smoke_check_rolls_back(setup):
    tmp_path, make = setup
    runner, _, registry = make(smoke=(False, "smoke check failed after 180s"))
    path = request(tmp_path)
    runner.run_once()
    rec = json.loads(path.read_text())
    assert rec["status"] == "rolled_back" and rec["rolled_back_to"] == "1"
    assert registry.rolled == 1


def test_failed_rollback_marks_request_failed(setup):
    tmp_path, make = setup
    runner, _, _ = make(smoke=(False, "bad"), registry=FakeRegistry(fail=True))
    path = request(tmp_path)
    runner.run_once()
    rec = json.loads(path.read_text())
    assert rec["status"] == "failed" and "rollback failed too" in rec["error"]


def test_failed_pipeline_reports_the_stage_error(setup):
    tmp_path, make = setup
    pipe = FakePipeline(tmp_path / "reports", code=1, stage_error="PM2.5 > 1000")
    runner, _, _ = make(pipeline=pipe)
    path = request(tmp_path)
    runner.run_once()
    rec = json.loads(path.read_text())
    assert rec["status"] == "failed"
    assert (
        "exited with 1" in rec["error"]
        and "stage features: PM2.5 > 1000" in rec["error"]
    )


def test_low_memory_stops_before_the_batch(setup):
    tmp_path, make = setup
    runner, pipeline, _ = make(free=1200)
    path = request(tmp_path)
    runner.run_once()
    rec = json.loads(path.read_text())
    assert rec["status"] == "failed" and "1200 MB free" in rec["error"]
    assert pipeline.calls == []
    assert ops.read_cutoff(tmp_path / "params.yaml") == "2020-03-24 23:00:00"


def test_stale_register_report_is_not_trusted(setup):
    tmp_path, make = setup

    class Stale(FakePipeline):
        def __call__(self, env, log_path):
            code = super().__call__(env, log_path)
            doc = json.loads((self.reports / "register.json").read_text())
            doc["cutoff"] = "2020-03-24 23:00:00"
            (self.reports / "register.json").write_text(json.dumps(doc))
            return code

    runner, _, _ = make(pipeline=Stale(tmp_path / "reports"))
    path = request(tmp_path)
    runner.run_once()
    assert "not from this run" in json.loads(path.read_text())["error"]


def test_only_queued_requests_run_and_recover_marks_running_failed(setup):
    tmp_path, make = setup
    runner, pipeline, _ = make()
    request(tmp_path, "rt-0", status="done")
    stale = request(tmp_path, "rt-1", status="running")
    (tmp_path / "ops" / "requests" / "rt-2.json").write_text("{broken")
    assert runner.pending() == []
    assert runner.recover() == 1
    assert json.loads(stale.read_text())["status"] == "failed"
    assert runner.run_once() == 0 and pipeline.calls == []


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)

    def predict(self, rows):
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return [answer]


def test_smoke_check_waits_for_the_new_version():
    client = FakeClient(
        [
            ModelUnavailableError("restarting"),
            {"pm25": 30.0, "model_version": "1"},
            {"pm25": 31.5, "model_version": "2"},
        ]
    )
    clock = iter(range(100))
    smoke = ops.SmokeCheck(
        client, {}, 60, sleep=lambda s: None, now=lambda: next(clock)
    )
    assert smoke("2") == (True, "version 2 answered 31.5")


def test_smoke_check_times_out():
    client = FakeClient([{"pm25": float("nan"), "model_version": "2"}] * 5)
    clock = iter([0, 0, 30, 61, 90])
    smoke = ops.SmokeCheck(
        client, {}, 60, sleep=lambda s: None, now=lambda: next(clock)
    )
    passed, message = smoke("2")
    assert passed is False and "after 60s" in message
