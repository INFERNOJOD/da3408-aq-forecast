"""Tests for the FastAPI backend: every endpoint in docs/LLD.md, with fakes."""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from src.backend import aqi
from src.backend.app import create_app
from src.backend.model_client import ModelServerClient, ModelUnavailableError
from src.backend.ops import EpisodeGate, RetrainQueue
from src.backend.registry_view import RegistryView
from src.backend.replay import ReplayClock
from src.backend.settings import Settings
from src.backend.store import ServingStore
from src.common.errors import RegistryError, RegistryUnavailableError
from src.common.schema import FEATURE_COLUMNS, FEATURES

KEY = "test-key"
AUTH = {"Authorization": f"Bearer {KEY}"}
CITIES = ("Delhi", "Chennai")
START = "2020-03-25 00:00:00"


class FakeModel:
    """Stands in for the model server client."""

    def __init__(self):
        self.up = True
        self.calls = []
        self.version = "3"

    def is_up(self):
        return self.up

    def predict(self, rows):
        self.calls.append(rows)
        if not self.up:
            raise ModelUnavailableError("down")
        return [
            {
                "pm25": 49.84 if r["horizon_h"] == 1 else -3.0,
                "model_version": self.version,
            }
            for r in rows
        ]


class FakeRegistry:
    """Stands in for ModelRegistryClient."""

    name = "aq-pm25"

    def __init__(self):
        self.rolled = []
        self.rows = [
            {
                "version": "3",
                "aliases": ["champion"],
                "mlflow_run_id": "run3",
                "created_ms": 1_700_000_000_000,
                "tags": {"git_commit": "abc1234def", "mae_1h": "6.21", "cutoff": "c"},
            },
            {
                "version": "2",
                "aliases": ["previous"],
                "mlflow_run_id": "run2",
                "created_ms": 1_600_000_000_000,
                "tags": {},
            },
        ]

    def versions(self):
        return self.rows

    def rollback(self, version):
        if version == "9":
            raise RegistryError("Version 9 does not exist")
        if version == "down":
            raise RegistryUnavailableError("MLflow is not reachable.")
        self.rolled.append(version)
        return "3", version or "2"


@pytest.fixture
def serving(tmp_path):
    """A small serving.parquet: two cities, three days from the replay start."""
    hours = pd.date_range(START, periods=72, freq="h")
    frames = []
    for code, city in enumerate(CITIES):
        df = pd.DataFrame({"City": city, "Datetime": hours})
        df["city_code"] = np.int32(code)
        for col in FEATURE_COLUMNS[1:]:
            df[col] = 10.0
        df["pm25"] = 52.34
        frames.append(df)
    full = pd.concat(frames, ignore_index=True)
    full.loc[(full.City == "Chennai") & (full.index % 72 == 0), "pm25_lag_168"] = np.nan
    full.loc[(full.City == "Chennai") & (full.index % 72 == 0), "pm25"] = np.nan
    path = tmp_path / "serving.parquet"
    full.to_parquet(path, index=False)
    return path


@pytest.fixture
def env(tmp_path, serving):
    """Return (client, fakes, settings) for a fresh app."""
    reports = tmp_path / "reports"
    reports.mkdir()
    settings = Settings(
        ops_api_key=KEY,
        cities=CITIES,
        model_name="aq-pm25",
        serving_path=serving,
        reports_dir=reports,
        ops_dir=tmp_path / "ops",
    )
    model, registry = FakeModel(), FakeRegistry()
    app = create_app(
        settings,
        store=ServingStore(serving),
        client=model,
        registry=RegistryView(registry),
    )
    return TestClient(app), model, registry, settings


def error_code(resp):
    return resp.json()["error"]["code"]


# ---- public endpoints -----------------------------------------------------


def test_health_ok_and_degraded(env):
    client, model, _, _ = env
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["model_server"] == "up"
    assert body["model_version"] == "3" and body["replay_running"] is False
    assert body["sim_time"] == "2020-03-25T00:00:00"
    model.up = False
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
    assert resp.json()["model_server"] == "down"


def test_cities(env):
    assert env[0].get("/cities").json() == {"cities": list(CITIES)}


def test_aqi_categories_match_hld(env):
    body = env[0].get("/aqi/categories").json()
    names = [c["name"] for c in body["categories"]]
    assert names == ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
    assert body["categories"][0]["min"] == 0 and body["categories"][0]["max"] == 30
    assert body["categories"][4]["min"] == 121 and body["categories"][4]["max"] == 250
    assert body["categories"][-1]["max"] is None
    assert "Indicative" in body["note"]


@pytest.mark.parametrize(
    "value,name",
    [(0, "Good"), (30.4, "Good"), (31, "Satisfactory"), (60.9, "Satisfactory"),
     (90, "Moderate"), (120, "Poor"), (250.5, "Very Poor"), (251, "Severe"),
     (900, "Severe")],
)  # fmt: skip
def test_categorize_edges(value, name):
    assert aqi.categorize(value)["aqi_category"] == name


def test_forecast_shape_and_values(env):
    client, model, _, _ = env
    body = client.get("/forecast", params={"city": "Delhi"}).json()
    assert body["city"] == "Delhi" and body["issued_at"] == "2020-03-25T00:00:00"
    assert body["latest_observed_pm25"] == 52.3
    one, day = body["forecasts"]
    assert one["horizon_h"] == 1 and one["valid_at"] == "2020-03-25T01:00:00"
    assert one["pm25"] == 49.8 and one["aqi_category"] == "Satisfactory"
    assert one["aqi_color"] == "#92D050" and one["advice"]
    assert day["valid_at"] == "2020-03-26T00:00:00"
    assert day["pm25"] == 0.0  # negative model output is clipped
    assert body["model"] == {
        "name": "aq-pm25",
        "version": "3",
        "mlflow_run_id": "run3",
        "git_commit": "abc1234",
    }
    # The model got one row per horizon with exactly the columns of the LLD.
    rows = model.calls[0]
    assert [r["horizon_h"] for r in rows] == [1, 24]
    assert set(rows[0]) >= set(FEATURES)


def test_forecast_null_observed_and_null_feature(env):
    client, model, _, _ = env
    body = client.get("/forecast", params={"city": "Chennai"}).json()
    assert body["latest_observed_pm25"] is None
    assert model.calls[0][0]["pm25_lag_168"] is None


@pytest.mark.parametrize("bad", ["Pune", "delhi", "", "Delhi%20", "' OR 1=1"])
def test_forecast_unknown_city_is_404(env, bad):
    resp = env[0].get("/forecast", params={"city": bad})
    assert resp.status_code == 404 and error_code(resp) == "UNKNOWN_CITY"


def test_forecast_missing_city_is_422(env):
    resp = env[0].get("/forecast")
    assert resp.status_code == 422 and error_code(resp) == "VALIDATION_ERROR"


def test_forecast_model_down_is_503(env):
    client, model, _, _ = env
    model.up = False
    resp = client.get("/forecast", params={"city": "Delhi"})
    assert resp.status_code == 503 and error_code(resp) == "MODEL_UNAVAILABLE"
    assert "aq_model_server_errors_total 1.0" in client.get("/metrics").text


def test_forecast_no_data_when_store_has_no_row(tmp_path, serving):
    settings = Settings(
        ops_api_key=KEY,
        cities=CITIES,
        model_name="aq-pm25",
        reports_dir=tmp_path,
        ops_dir=tmp_path,
        replay_start="2021-01-01 00:00:00",
        replay_end="2021-01-02 00:00:00",
    )
    app = create_app(
        settings,
        store=ServingStore(serving),
        client=FakeModel(),
        registry=RegistryView(FakeRegistry()),
    )
    resp = TestClient(app).get("/forecast", params={"city": "Delhi"})
    assert resp.status_code == 503 and error_code(resp) == "NO_DATA"


def test_unknown_route_and_method_use_error_body(env):
    client = env[0]
    resp = client.get("/nope")
    assert resp.status_code == 404 and error_code(resp) == "NOT_FOUND"
    resp = client.post("/cities")
    assert resp.status_code == 405 and "error" in resp.json()


# ---- pipeline endpoints ---------------------------------------------------


def write_runs(reports: Path, records):
    (reports / "runs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def rec(run_id, stage, status="success", **extra):
    base = {
        "run_id": run_id, "trigger": "manual", "stage": stage, "status": status,
        "started_at": "2026-10-20T10:00:00", "duration_s": 2.0, "rows_in": 10,
        "rows_out": 10, "rows_per_sec": 5.0, "error": None,
        "git_commit": "abc1234", "cutoff": "2020-03-24 23:00:00",
    }  # fmt: skip
    return {**base, **extra}


def test_pipeline_stages_and_runs(env):
    client, _, _, settings = env
    assert client.get("/pipeline/stages").json()["run_id"] is None
    stages = ["ingest", "validate", "features", "train", "evaluate", "test", "register"]
    write_runs(
        settings.reports_dir,
        [rec("r1", s) for s in stages]
        + [rec("r2", "ingest"), rec("r2", "validate", "failed", error="PM2.5 > 1000")],
    )
    (settings.reports_dir / "register.json").write_text(
        json.dumps({"promoted": False, "mlflow_run_id": "abc"})
    )
    st = client.get("/pipeline/stages").json()
    assert st["run_id"] == "r2"
    by = {s["name"]: s for s in st["stages"]}
    assert [s["name"] for s in st["stages"]] == stages
    assert by["validate"]["status"] == "failed" and by["validate"]["deps"] == ["ingest"]
    assert by["train"]["status"] == "not_run" and by["train"]["duration_s"] is None
    runs = client.get("/pipeline/runs").json()["runs"]
    assert [r["run_id"] for r in runs] == ["r2", "r1"]
    assert runs[0]["status"] == "failed" and runs[0]["failed_stage"] == "validate"
    assert runs[0]["error"] == "PM2.5 > 1000" and runs[0]["promoted"] is None
    assert runs[1]["status"] == "success" and runs[1]["promoted"] is None
    # A newest run that skipped register does not borrow register.json.
    write_runs(settings.reports_dir, [rec("r1", "ingest"), rec("r3", "train")])
    newest = client.get("/pipeline/runs").json()["runs"][0]
    assert newest["status"] == "success" and newest["promoted"] is None
    write_runs(settings.reports_dir, [rec("r4", "register")])
    newest = client.get("/pipeline/runs").json()["runs"][0]
    assert newest["promoted"] is False and newest["mlflow_run_id"] == "abc"
    assert len(client.get("/pipeline/runs?limit=1").json()["runs"]) == 1


def test_pipeline_runs_skips_bad_lines(env):
    client, _, _, settings = env
    good = json.dumps(rec("r1", "ingest"))
    (settings.reports_dir / "runs.jsonl").write_text(f"{{broken\n{good}\n")
    assert [r["run_id"] for r in client.get("/pipeline/runs").json()["runs"]] == ["r1"]


@pytest.mark.parametrize("limit", ["0", "101", "abc", "-1"])
def test_pipeline_runs_bad_limit_is_422(env, limit):
    resp = env[0].get(f"/pipeline/runs?limit={limit}")
    assert resp.status_code == 422 and error_code(resp) == "VALIDATION_ERROR"


def test_pipeline_models(env):
    models = env[0].get("/pipeline/models").json()["models"]
    assert [m["version"] for m in models] == ["3", "2"]
    assert models[0]["aliases"] == ["champion"] and models[0]["mae_1h"] == 6.21
    assert models[0]["git_commit"] == "abc1234" and models[0]["mae_24h"] is None
    assert models[0]["created_at"].startswith("2023-")


def test_registry_failure_does_not_break_forecast(tmp_path, serving):
    class Broken:
        name = "aq-pm25"

        def versions(self):
            raise RuntimeError("registry down")

    settings = Settings(ops_api_key=KEY, cities=CITIES, model_name="aq-pm25",
                        reports_dir=tmp_path, ops_dir=tmp_path)  # fmt: skip
    app = create_app(settings, store=ServingStore(serving), client=FakeModel(),
                     registry=RegistryView(Broken()))  # fmt: skip
    body = TestClient(app).get("/forecast", params={"city": "Delhi"}).json()
    assert body["model"]["mlflow_run_id"] is None and body["model"]["version"] == "3"


# ---- ops: auth ------------------------------------------------------------

OPS_CALLS = [
    ("get", "/ops/drift", None),
    ("get", "/ops/replay", None),
    ("post", "/ops/replay", {"action": "stop"}),
    ("post", "/ops/retrain", {"reason": "x"}),
    ("post", "/ops/rollback", {}),
    ("post", "/ops/alerts", {"alerts": []}),
]


@pytest.mark.parametrize("method,path,body", OPS_CALLS)
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": KEY},
     {"Authorization": f"Basic {KEY}"}, {"Authorization": "Bearer "}],
)  # fmt: skip
def test_ops_requires_key(env, method, path, body, headers):
    resp = getattr(env[0], method)(
        path, headers=headers, **({"json": body} if body is not None else {})
    )
    assert resp.status_code == 401 and error_code(resp) == "UNAUTHORIZED"


def test_empty_key_refused(env):
    settings = env[3]
    with pytest.raises(ValueError):
        create_app(Settings(**{**settings.__dict__, "ops_api_key": ""}))


# ---- ops: drift, replay, retrain, rollback, alerts ------------------------


def test_ops_drift_shape(env):
    body = env[0].get("/ops/drift", headers=AUTH).json()
    assert body["window_h"] == 168 and body["min_cities"] == 4
    assert body["mae_ratio_threshold"] == 1.5 and body["reference_block"] == 0
    assert [c["city"] for c in body["cities"]] == list(CITIES)
    assert set(body["cities"][0]) == {
        "city", "psi", "psi_threshold", "exceeds", "votes", "mae_ratio_1h",
    }  # fmt: skip
    assert body["any_drift"] is False and body["psi_condition"] is False


def test_ops_drift_reads_thresholds_file(env):
    client, _, _, settings = env
    (settings.reports_dir / "drift_thresholds.json").write_text(
        json.dumps({"cities": {"Delhi": {"psi_threshold": 1.9}}})
    )
    cities = client.get("/ops/drift", headers=AUTH).json()["cities"]
    assert cities[0]["psi_threshold"] == 1.9 and cities[1]["psi_threshold"] is None


def test_replay_start_stop_reset_and_conflicts(env):
    client = env[0]
    start = client.post(
        "/ops/replay", json={"action": "start", "speed_hps": 2.5}, headers=AUTH
    )
    assert start.status_code == 200
    assert start.json()["running"] is True and start.json()["speed_hps"] == 2.5
    assert start.json()["end"] == "2020-06-30T23:00:00"
    dup = client.post("/ops/replay", json={"action": "start"}, headers=AUTH)
    assert dup.status_code == 409 and error_code(dup) == "CONFLICT"
    assert client.get("/ops/replay", headers=AUTH).json()["running"] is True
    assert (
        client.post("/ops/replay", json={"action": "stop"}, headers=AUTH).status_code
        == 200
    )
    again = client.post("/ops/replay", json={"action": "stop"}, headers=AUTH)
    assert again.status_code == 409
    reset = client.post("/ops/replay", json={"action": "reset"}, headers=AUTH).json()
    assert reset["sim_time"] == "2020-03-25T00:00:00" and reset["running"] is False


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"action": "jump"},
        {"action": "start", "speed_hps": 0},
        {"action": "start", "speed_hps": 21},
        {"action": "start", "speed_hps": "fast"},
        {"action": 3},
        [],
    ],
)
def test_replay_bad_body_is_422(env, body):
    resp = env[0].post("/ops/replay", json=body, headers=AUTH)
    assert resp.status_code == 422 and error_code(resp) == "VALIDATION_ERROR"


def test_replay_malformed_json_is_422(env):
    resp = env[0].post(
        "/ops/replay",
        content=b"{not json",
        headers={**AUTH, "Content-Type": "application/json"},
    )
    assert resp.status_code == 422 and error_code(resp) == "VALIDATION_ERROR"


def test_retrain_creates_file_then_conflicts(env):
    client, _, _, settings = env
    resp = client.post("/ops/retrain", json={"reason": "manual"}, headers=AUTH)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued" and body["cutoff"] == "2020-03-25T00:00:00"
    saved = json.loads(
        (settings.ops_dir / "requests" / f"{body['request_id']}.json").read_text()
    )
    assert saved["reason"] == "manual" and saved["status"] == "queued"
    assert saved["trigger"] == "manual" and saved["drift"] == {}
    again = client.post("/ops/retrain", json={"reason": "again"}, headers=AUTH)
    assert again.status_code == 409 and error_code(again) == "CONFLICT"


@pytest.mark.parametrize(
    "body", [{}, {"reason": ""}, {"reason": "x" * 201}, {"reason": 5}]
)
def test_retrain_bad_body_is_422(env, body):
    resp = env[0].post("/ops/retrain", json=body, headers=AUTH)
    assert resp.status_code == 422 and error_code(resp) == "VALIDATION_ERROR"


def test_rollback_default_named_and_missing(env):
    client, _, registry, _ = env
    assert client.post("/ops/rollback", json={}, headers=AUTH).json() == {
        "from_version": "3", "to_version": "2",
    }  # fmt: skip
    named = client.post("/ops/rollback", json={"version": "1"}, headers=AUTH)
    assert named.json()["to_version"] == "1" and registry.rolled == [None, "1"]
    bad = client.post("/ops/rollback", json={"version": "9"}, headers=AUTH)
    assert bad.status_code == 400 and error_code(bad) == "BAD_REQUEST"


def test_rollback_with_registry_down_is_503(env):
    resp = env[0].post("/ops/rollback", json={"version": "down"}, headers=AUTH)
    assert resp.status_code == 503 and error_code(resp) == "REGISTRY_UNAVAILABLE"
    assert "not reachable" in resp.json()["error"]["message"]


def test_openapi_lists_503_for_rollback(env):
    spec = env[0].get("/openapi.json").json()
    assert "503" in spec["paths"]["/ops/rollback"]["post"]["responses"]


def alert(name="PM25DriftHigh", status="firing", action="retrain"):
    labels = {"alertname": name, **({"action": action} if action else {})}
    return {"status": status, "labels": labels}


def test_alerts_trigger_retrain_once_then_cooldown(env):
    client, _, _, settings = env
    payload = {"version": "4", "alerts": [alert(), alert("TargetDown", action=None)]}
    first = client.post("/ops/alerts", json=payload, headers=AUTH).json()
    assert first == {"received": 2, "retrain_requested": True}
    files = list((settings.ops_dir / "requests").glob("*.json"))
    saved = json.loads(files[0].read_text())
    assert saved["reason"] == "drift_alert:PM25DriftHigh"
    assert saved["trigger"] == "drift_alert" and saved["drift"] == {
        "cities_exceeding": 0
    }
    second = client.post("/ops/alerts", json=payload, headers=AUTH).json()
    assert second["retrain_requested"] is False


def test_alerts_ignore_resolved_and_unlabelled(env):
    client = env[0]
    payload = {
        "alerts": [alert(status="resolved"), alert("ForecastErrorHigh", action=None)]
    }
    body = client.post("/ops/alerts", json=payload, headers=AUTH).json()
    assert body == {"received": 2, "retrain_requested": False}


def test_alerts_bad_payload_is_422(env):
    resp = env[0].post("/ops/alerts", json={"alerts": "no"}, headers=AUTH)
    assert resp.status_code == 422


# ---- metrics --------------------------------------------------------------


def test_metrics_endpoint_lists_lld_metrics(env):
    client = env[0]
    client.get("/forecast", params={"city": "Delhi"})
    client.get("/cities")
    text = client.get("/metrics").text
    for name in [
        "aq_http_requests_total", "aq_http_request_duration_seconds",
        "aq_forecast_pm25", "aq_drift_detected", "aq_drift_cities_exceeding",
        "aq_model_version 3.0", "aq_replay_sim_time_seconds",
        "process_resident_memory_bytes",
    ]:  # fmt: skip
        assert name in text
    assert 'path="/cities"' in text and 'status="200"' in text
    assert 'aq_forecast_pm25{city="Delhi",horizon_h="24"} 0.0' in text


def test_metrics_path_label_is_the_route_template(env):
    client = env[0]
    for city in ["a", "b", "c"]:
        client.get(f"/nothing/{city}")
    text = client.get("/metrics").text
    assert 'path="unmatched"' in text and "/nothing/a" not in text


def test_unexpected_error_becomes_500_without_details(env):
    client, model, _, _ = env

    def boom(rows):
        raise KeyError("secret internals")

    model.predict = boom
    quiet = TestClient(client.app, raise_server_exceptions=False)
    resp = quiet.get("/forecast", params={"city": "Delhi"})
    assert resp.status_code == 500 and error_code(resp) == "INTERNAL_ERROR"
    assert "secret" not in resp.text


# ---- units: replay clock, queue, model client, settings -------------------


class Ticker:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make_clock(ticker, end="2020-03-26 00:00:00"):
    return ReplayClock(datetime(2020, 3, 25), datetime.fromisoformat(end), 1.0, ticker)


def test_clock_advances_with_speed_and_stops_at_end():
    ticker = Ticker()
    clock = make_clock(ticker)
    assert not clock.running and clock.sim_time == datetime(2020, 3, 25)
    clock.apply("start", 2.0)
    ticker.t = 5.0
    assert clock.sim_time == datetime(2020, 3, 25, 10)
    clock.apply("stop")
    ticker.t = 100.0
    assert clock.replay_hour == 10  # stopped clocks do not move
    clock.apply("start", 20.0)
    ticker.t = 200.0  # would be far past the 24 h replay
    assert clock.sim_time == datetime(2020, 3, 26)
    assert clock.running is False  # stopped by itself at the end
    assert clock.apply("reset")["sim_time"] == "2020-03-25T00:00:00"


def test_queue_cooldown_and_active(tmp_path):
    moment = {"now": datetime(2026, 10, 20, 10, 0, 0)}
    queue = RetrainQueue(tmp_path, 30, lambda: moment["now"])
    assert not queue.in_cooldown() and not queue.has_active()
    record = queue.create("manual", "c")
    assert queue.has_active() and queue.in_cooldown()
    path = tmp_path / "requests" / f"{record['request_id']}.json"
    path.write_text(json.dumps({**record, "status": "done"}))
    assert not queue.has_active() and queue.in_cooldown()
    moment["now"] = datetime(2026, 10, 20, 10, 31, 0)
    assert not queue.in_cooldown()


def test_queue_ignores_unreadable_file(tmp_path):
    (tmp_path / "requests").mkdir()
    (tmp_path / "requests" / "bad.json").write_text("{nope")
    queue = RetrainQueue(tmp_path, 30)
    assert not queue.has_active() and not queue.in_cooldown()


class FakeResp:
    def __init__(self, status=200, payload=None, bad=False):
        self.status_code, self._payload, self._bad = status, payload, bad

    def json(self):
        if self._bad:
            raise ValueError("no json")
        return self._payload


def test_model_client_success_and_failures(monkeypatch):
    import requests

    rows = [{c: 1 for c in FEATURES}] * 2
    seen = {}

    def ok(url, json, timeout):
        seen.update(url=url, body=json)
        return FakeResp(payload={"predictions": [{"pm25": 1}, {"pm25": 2}]})

    monkeypatch.setattr(requests, "post", ok)
    client = ModelServerClient("http://m:5001/")
    assert len(client.predict(rows)) == 2
    assert seen["url"] == "http://m:5001/invocations"
    assert seen["body"]["dataframe_split"]["columns"] == FEATURES

    for response in [
        FakeResp(status=500), FakeResp(bad=True), FakeResp(payload={}),
        FakeResp(payload={"predictions": [{"pm25": 1}]}),
    ]:  # fmt: skip
        monkeypatch.setattr(requests, "post", lambda *a, r=response, **k: r)
        with pytest.raises(ModelUnavailableError):
            client.predict(rows)

    def refuse(*a, **k):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", refuse)
    monkeypatch.setattr(requests, "get", refuse)
    with pytest.raises(ModelUnavailableError):
        client.predict(rows)
    assert client.is_up() is False
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp())
    assert client.is_up() is True


def test_settings_from_env_requires_key(monkeypatch):
    from src.common.errors import ConfigError

    monkeypatch.delenv("OPS_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        Settings.from_env()
    monkeypatch.setenv("OPS_API_KEY", "k")
    monkeypatch.setenv("MODEL_SERVER_URL", "http://x:1")
    settings = Settings.from_env()
    assert settings.model_server_url == "http://x:1" and len(settings.cities) == 7


def test_store_missing_file_raises(tmp_path):
    from src.common.errors import ConfigError

    with pytest.raises(ConfigError):
        ServingStore(tmp_path / "none.parquet")


def test_lld_lists_the_backend_routes(env):
    """Every route of the app is documented in docs/LLD.md."""
    lld = (Path(__file__).parents[1] / "docs" / "LLD.md").read_text()
    for route in env[0].app.routes:
        path = getattr(route, "path", "")
        if path.startswith(
            ("/ops", "/pipeline", "/aqi", "/health", "/cities", "/forecast", "/metrics")
        ):
            assert path in lld, path


def test_openapi_documents_the_lld_error_responses(env):
    """/openapi.json shows the LLD error body and codes, not FastAPI's defaults."""
    spec = env[0].get("/openapi.json").json()
    expected = {
        ("get", "/forecast"): {"404", "422", "503", "500"},
        ("get", "/pipeline/runs"): {"422", "500"},
        ("get", "/ops/drift"): {"401", "422", "500"},
        ("post", "/ops/replay"): {"401", "409", "422", "500"},
        ("post", "/ops/retrain"): {"401", "409", "422", "500"},
        ("post", "/ops/rollback"): {"400", "401", "422", "500"},
    }
    for (method, path), codes in expected.items():
        responses = spec["paths"][path][method]["responses"]
        assert codes <= set(responses), (method, path)
        for code in codes:
            ref = responses[code]["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("/ErrorBody"), (method, path, code)
    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_episode_gate_closes_after_quiet_period(tmp_path):
    gate = EpisodeGate(tmp_path, 72)
    t0 = datetime(2020, 4, 1)
    gate.observe(False, t0)  # nothing open: ignored
    assert not gate.is_open()
    gate.open_episode()
    assert gate.is_open()
    gate.observe(False, t0)  # quiet starts
    gate.observe(False, datetime(2020, 4, 3, 23))  # 71 h: still open
    assert gate.is_open()
    gate.observe(True, datetime(2020, 4, 4))  # drift again: quiet count restarts
    gate.observe(False, datetime(2020, 4, 4, 1))
    gate.observe(False, datetime(2020, 4, 7, 0))  # 71 h since 4 Apr 01:00
    assert gate.is_open()
    gate.observe(False, datetime(2020, 4, 7, 1))
    assert not gate.is_open()
    assert not EpisodeGate(tmp_path, 72).is_open()  # state survives a restart


def test_alerts_one_retrain_per_episode(tmp_path):
    moment = {"now": datetime(2026, 10, 20, 10, 0, 0)}
    gate = EpisodeGate(tmp_path, 72)
    queue = RetrainQueue(tmp_path, 30, lambda: moment["now"], episode=gate)
    payload = [alert()]
    assert queue.from_alerts(payload, "2020-04-01 00:00:00") is True
    record = json.loads(next((tmp_path / "requests").glob("*.json")).read_text())
    (tmp_path / "requests" / f"{record['request_id']}.json").write_text(
        json.dumps({**record, "status": "done"})
    )
    moment["now"] = datetime(2026, 10, 20, 12, 0, 0)  # cooldown is over
    assert queue.from_alerts(payload, "2020-04-02 00:00:00") is False  # same episode
    gate.observe(False, datetime(2020, 4, 5))
    gate.observe(False, datetime(2020, 4, 8))  # rule false for 72 h
    assert queue.from_alerts(payload, "2020-04-09 00:00:00") is True
