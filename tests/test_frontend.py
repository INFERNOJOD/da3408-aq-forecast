"""Tests for the frontend: the REST client, the helpers and both pages."""

import pytest
import requests
from prometheus_client import REGISTRY
from src.frontend import console_page, forecast_page
from src.frontend.client import BackendClient, BackendError
from src.frontend.helpers import (
    card_html,
    count_runs,
    dag_dot,
    drift_rows,
    horizon_label,
    nice_time,
    ops_message,
    short_time,
    text_color,
)
from streamlit.testing.v1 import AppTest

FORECAST = {
    "city": "Delhi",
    "issued_at": "2020-03-25T14:00:00",
    "latest_observed_pm25": 52.3,
    "forecasts": [
        {"horizon_h": 1, "valid_at": "2020-03-25T15:00:00", "pm25": 49.8,
         "aqi_category": "Satisfactory", "aqi_color": "#92D050",
         "advice": "Minor breathing discomfort <b>to</b> sensitive people."},
        {"horizon_h": 24, "valid_at": "2020-03-26T14:00:00", "pm25": 140.0,
         "aqi_category": "Very Poor", "aqi_color": "#FF0000", "advice": "Stay in."},
    ],
}  # fmt: skip


class FakeResponse:
    def __init__(self, status=200, payload=None, bad=False):
        self.status_code, self._payload, self._bad = status, payload, bad

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.response


def sample(name):
    return REGISTRY.get_sample_value(name, {"endpoint": "/forecast"}) or 0.0


# ---- client ---------------------------------------------------------------


def test_client_get_sends_no_key_unless_given():
    session = FakeSession(FakeResponse(payload={"cities": ["Delhi"]}))
    client = BackendClient("http://backend:8000/", session=session)
    assert client.get("/cities") == {"cities": ["Delhi"]}
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("GET", "http://backend:8000/cities")
    assert kwargs["headers"] == {}
    client.get("/ops/drift", api_key="k")
    assert session.calls[1][2]["headers"] == {"Authorization": "Bearer k"}


def test_client_reads_backend_url_and_ca_from_env(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "https://backend:8000/")
    monkeypatch.setenv("BACKEND_CA_FILE", "/certs/ca.crt")
    client = BackendClient(session=FakeSession())
    assert client.base_url == "https://backend:8000"
    assert client.verify == "/certs/ca.crt"


def test_client_maps_error_body():
    body = {"error": {"code": "UNKNOWN_CITY", "message": "City 'X' is not supported."}}
    client = BackendClient("http://b", session=FakeSession(FakeResponse(404, body)))
    with pytest.raises(BackendError) as info:
        client.get("/forecast", params={"city": "X"})
    assert info.value.code == "UNKNOWN_CITY" and info.value.status == 404


def test_client_unreachable_and_bad_json_are_counted():
    before = sample("aq_ui_backend_errors_total")
    down = BackendClient(
        "http://b", session=FakeSession(error=requests.ConnectionError())
    )
    with pytest.raises(BackendError) as info:
        down.get("/forecast?city=Delhi")
    assert info.value.code == "UNREACHABLE" and info.value.status is None
    bad = BackendClient("http://b", session=FakeSession(FakeResponse(bad=True)))
    with pytest.raises(BackendError) as info:
        bad.get("/forecast")
    assert info.value.code == "BAD_RESPONSE"
    assert sample("aq_ui_backend_errors_total") == before + 2


def test_client_times_calls():
    before = sample("aq_ui_backend_call_duration_seconds_count")
    BackendClient("http://b", session=FakeSession(FakeResponse(payload={}))).get(
        "/forecast", params={"city": "Delhi"}
    )
    assert sample("aq_ui_backend_call_duration_seconds_count") == before + 1


# ---- helpers --------------------------------------------------------------


def test_text_color_picks_readable_ink():
    assert text_color("#92D050") == "#000000"
    assert text_color("#C00000") == "#ffffff"


def test_nice_time_and_horizon_label():
    assert nice_time("2020-03-25T14:00:00") == "25 Mar 2020, 14:00"
    assert nice_time(None) == "unknown" and nice_time("junk") == "unknown"
    assert short_time("2020-03-25T14:00:00") == "25 Mar, 14:00"
    assert short_time(None) == "unknown"
    assert horizon_label(1) == "In 1 hour" and horizon_label(24) == "In 24 hours"


def test_card_html_has_colour_and_escapes_advice():
    html = card_html(FORECAST["forecasts"][0])
    assert "background:#92D050" in html and "49.8" in html and "Satisfactory" in html
    assert "<b>to</b>" not in html and "&lt;b&gt;" in html


def test_dag_dot_colours_and_edges():
    stages = [
        {"name": "ingest", "deps": [], "status": "success"},
        {"name": "validate", "deps": ["ingest"], "status": "failed"},
    ]
    dot = dag_dot(stages)
    assert '"ingest" -> "validate";' in dot
    assert '"validate" [fillcolor="#c62828"' in dot
    assert 'fillcolor="#2e7d32"' in dot


def test_count_runs():
    assert count_runs([{"status": "failed"}, {"status": "success"}, {}]) == (2, 1)


def test_ops_message_is_a_plain_sentence_for_each_ops_call():
    rollback = {"from_version": "4", "to_version": "1"}
    assert ops_message("Rolled back", "/ops/rollback", rollback) == (
        "Rolled back from version 4 to version 1."
    )
    retrain = {"request_id": "rt-1", "cutoff": "2020-04-02T23:00:00"}
    retrain["status"] = "queued"
    assert ops_message("Retrain requested", "/ops/retrain", retrain) == (
        "Retrain requested: request rt-1, with data up to 02 Apr 2020, 23:00. "
        "It is queued for the ops runner."
    )
    replay = {"running": False, "sim_time": "2020-03-25T00:00:00", "speed_hps": 2.5}
    assert ops_message("Replay reset", "/ops/replay", replay) == (
        "Replay reset. The replay clock is at 25 Mar 2020, 00:00, "
        "2.5 simulated hours per second."
    )
    replay["speed_hps"] = 1.0
    assert ops_message("Replay started", "/ops/replay", replay).endswith(
        "00:00, 1 simulated hour per second."
    )


def test_ops_message_falls_back_to_the_label_without_the_raw_dict():
    assert ops_message("Rolled back", "/ops/rollback", {"ok": True}) == "Rolled back."
    assert ops_message("Replay stopped", "/ops/replay", None) == "Replay stopped."
    assert ops_message("Done", "/ops/other", {"a": 1}) == "Done."


def test_drift_rows_show_a_dash_for_null_and_yes_no_for_flags():
    rows = drift_rows(
        [{"city": "Kolkata", "psi": None, "psi_threshold": None, "exceeds": None,
          "votes": False, "mae_ratio_1h": 0.64},
         {"city": "Delhi", "psi": 3.37, "psi_threshold": 2.0307, "exceeds": True,
          "votes": True, "mae_ratio_1h": None}]
    )  # fmt: skip
    assert rows[0] == {"city": "Kolkata", "psi": "–", "psi_threshold": "–",
                       "exceeds": "–", "votes": "no",
                       "mae_ratio_1h": "0.64"}  # fmt: skip
    assert rows[1]["psi"] == "3.37" and rows[1]["exceeds"] == "yes"
    assert rows[1]["mae_ratio_1h"] == "–"


# ---- pages (Streamlit's AppTest, with a fake backend) ----------------------


class FakeBackend:
    """Stands in for BackendClient inside the page functions."""

    def __init__(
        self, down=False, model_down=False, replay_running=False, health_down=False
    ):
        self.down, self.model_down, self.posts = down, model_down, []
        self.replay_running, self.health_down = replay_running, health_down

    def get(self, path, params=None, api_key=None):
        if self.down:
            raise BackendError("UNREACHABLE", "The backend does not answer.")
        if path == "/cities":
            return {"cities": ["Delhi", "Chennai"]}
        if path == "/forecast":
            if self.model_down:
                raise BackendError("MODEL_UNAVAILABLE", "x", 503)
            return {**FORECAST, "city": params["city"]}
        if path == "/aqi/categories":
            return {"categories": [{"name": "Good", "min": 0, "max": 30,
                                    "color": "#00B050", "advice": "ok"}],
                    "note": "Indicative."}  # fmt: skip
        if path == "/health":
            if self.health_down:
                raise BackendError("UNREACHABLE", "The backend does not answer.")
            return {"status": "ok", "model_server": "up", "model_version": "4",
                    "sim_time": "2020-04-01T00:00:00",
                    "replay_running": self.replay_running}  # fmt: skip
        if path == "/pipeline/stages":
            return {"run_id": "r1", "stages": [
                {"name": "ingest", "deps": [], "status": "success", "duration_s": 1.0,
                 "rows_out": 10, "rows_per_sec": 10}]}  # fmt: skip
        if path == "/pipeline/runs":
            return {"runs": [
                {"run_id": "r2", "status": "success", "started_at": "t2",
                 "failed_stage": None, "error": None},
                {"run_id": "r1", "status": "failed", "started_at": "t1",
                 "failed_stage": "validate", "error": "boom"}]}  # fmt: skip
        if path == "/pipeline/models":
            return {"models": [{"version": "4", "aliases": ["champion"]}]}
        if path == "/ops/drift":
            if api_key != "good":
                raise BackendError("UNAUTHORIZED", "Missing or wrong API key.", 401)
            return {"any_drift": True, "cities_exceeding": 4, "min_cities": 4,
                    "mae_ratio_pooled": None, "sim_time": "2020-04-01T00:00:00",
                    "cities": [
                        {"city": "Delhi", "psi": 3.4, "psi_threshold": 2.0307,
                         "exceeds": True, "votes": True},
                        {"city": "Kolkata", "psi": None, "psi_threshold": None,
                         "exceeds": None, "votes": False}]}  # fmt: skip
        raise AssertionError(path)

    def post(self, path, body, api_key=None):
        # Response shapes from docs/LLD.md section 3.
        self.posts.append((path, body, api_key))
        if path == "/ops/rollback":
            return {"from_version": "4", "to_version": "1"}
        if path == "/ops/retrain":
            return {"request_id": "rt-20261105-120000",
                    "cutoff": "2020-04-01T00:00:00", "status": "queued"}  # fmt: skip
        return {"running": True, "sim_time": "2020-04-01T00:00:00",
                "speed_hps": 1.0}  # fmt: skip


def forecast_app(backend):
    from src.frontend import forecast_page as page

    page._forecast.clear()
    page._static.clear()
    page.render_forecast(backend)


def console_app(backend):
    from src.frontend import console_page as page

    page.render_console(backend)


def run_forecast(backend):
    at = AppTest.from_function(forecast_app, args=(backend,))
    return at.run()


def test_forecast_page_shows_cards_for_chosen_city():
    at = run_forecast(FakeBackend())
    assert not at.exception
    assert at.selectbox[0].options == ["Delhi", "Chennai"]
    cards = [
        m.value for m in at.markdown if "µg/m³" in m.value and "background" in m.value
    ]
    assert len(cards) == 2 and "Very Poor" in cards[1]
    at.selectbox[0].select("Chennai").run()
    assert not at.exception


def test_forecast_page_says_it_is_a_2020_demo():
    at = run_forecast(FakeBackend())
    assert "March to June 2020" in at.info[0].value


def captions(at):
    return [c.value for c in at.caption]


def test_forecast_page_says_when_the_demo_clock_is_paused():
    at = run_forecast(FakeBackend(replay_running=False))
    assert not at.exception
    assert any("Demo clock is paused" in c for c in captions(at))
    assert not any("Replay running" in c for c in captions(at))


def test_forecast_page_says_when_the_replay_is_running():
    at = run_forecast(FakeBackend(replay_running=True))
    assert any("Replay running" in c for c in captions(at))
    assert not any("paused" in c for c in captions(at))


def test_forecast_page_still_shows_cards_when_health_fails():
    at = run_forecast(FakeBackend(health_down=True))
    assert not at.exception and not at.error
    assert not any("paused" in c or "Replay running" in c for c in captions(at))
    assert any("Forecast made for" in c for c in captions(at))


def test_app_serves_forecast_and_console_paths(monkeypatch):
    # The default page lives at "/" and ignores url_path, so it must not be
    # Forecast itself: "/" redirects, "/forecast" and "/console" are real pages.
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("UI_METRICS_PORT", "0")
    at = AppTest.from_file("../src/frontend/app.py").run()
    assert not at.exception
    assert at.title[0].value == "Air quality forecast"  # "/" landed on Forecast
    # AppTest.switch_page() only knows file pages, so open the paths by hash.
    paths = {i["url_pathname"]: h for h, i in at._registered_pages.items()}
    assert set(paths) == {"", "forecast", "console"}
    for path, title in [
        ("forecast", "Air quality forecast"),
        ("console", "Pipeline console"),
    ]:
        at._page_hash = paths[path]
        at.run()
        assert not at.exception
        assert at.title[0].value == title


def test_forecast_page_friendly_message_when_backend_down():
    at = run_forecast(FakeBackend(down=True))
    assert not at.exception
    assert "not reachable" in at.error[0].value
    assert not at.selectbox


def test_forecast_page_friendly_message_when_model_down():
    at = run_forecast(FakeBackend(model_down=True))
    assert "taking a break" in at.error[0].value


def test_console_hides_ops_until_key_and_rejects_wrong_key():
    backend = FakeBackend()
    at = AppTest.from_function(console_app, args=(backend,)).run()
    assert not at.exception
    assert "Enter the API key" in at.info[0].value
    assert not at.button  # no ops buttons without a key
    at.text_input[0].set_value("bad").run()
    assert any("API key is wrong" in e.value for e in at.error)
    assert not at.button


def test_console_lists_failed_runs_with_their_error_and_a_short_replay_time():
    at = AppTest.from_function(console_app, args=(FakeBackend(),)).run()
    assert not at.exception
    assert any("1 successful, 1 failed" in m.value for m in at.markdown)
    tables = [t.value for t in at.dataframe]
    failed = next(t for t in tables if list(t.columns)[-1] == "error")
    assert failed["error"].tolist() == ["boom"]
    assert failed["failed_stage"].tolist() == ["validate"]
    assert any(
        m.label == "Replay time" and m.value == "01 Apr, 00:00" for m in at.metric
    )
    assert any("01 Apr 2020, 00:00" in c.value for c in at.caption)


def test_console_status_boxes_are_two_per_row():
    # In one row of four, "Replay time" was cut off in a real browser
    # (screenshot 08). Each status box must sit in a half-width column.
    at = AppTest.from_function(console_app, args=(FakeBackend(),)).run()
    boxes = {m.label: col.weight for col in at.columns for m in col.get("metric")}
    status = ["Backend", "Model server", "Champion version", "Replay time"]
    assert {label: boxes[label] for label in status} == dict.fromkeys(status, 0.5)


def test_console_with_key_shows_drift_and_posts_retrain():
    backend = FakeBackend()
    at = AppTest.from_function(console_app, args=(backend,)).run()
    at.text_input[0].set_value("good").run()
    assert not at.exception
    assert any(m.label == "Drift detected" and m.value == "YES" for m in at.metric)
    drift = next(t.value for t in at.dataframe if "psi" in t.value.columns)
    assert drift.loc[1, "psi_threshold"] == "–" and drift.loc[1, "exceeds"] == "–"
    assert "None" not in drift.to_string()
    next(b for b in at.button if b.label == "Retrain now").click().run()
    assert backend.posts[0][0] == "/ops/retrain" and backend.posts[0][2] == "good"
    next(b for b in at.button if b.label == "Roll back").click().run()
    assert backend.posts[1] == ("/ops/rollback", {}, "good")
    # The result is a sentence, not the raw response dict.
    assert at.success[0].value == "Rolled back from version 4 to version 1."


def test_modules_import():
    assert forecast_page.DOWN_MESSAGE and console_page.LINKS


def test_main_starts_exporter_before_streamlit(monkeypatch):
    from src.frontend import main as entry

    calls = []
    monkeypatch.setattr(entry.metrics, "start_exporter", lambda: calls.append("exp"))
    monkeypatch.setattr(entry.stcli, "main", lambda: calls.append(list(entry.sys.argv)))
    monkeypatch.setattr(entry.sys, "argv", ["main.py", "--server.port=8501"])
    with pytest.raises(SystemExit):
        entry.main()
    assert calls[0] == "exp"
    assert calls[1][:2] == ["streamlit", "run"]
    assert (
        calls[1][2].endswith("src/frontend/app.py")
        and calls[1][3] == "--server.port=8501"
    )


def test_streamlit_config_hides_developer_toolbar():
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / ".streamlit/config.toml").read_text())
    assert config["client"]["toolbarMode"] == "minimal"
    dockerfile = (root / "docker/frontend/Dockerfile").read_text()
    assert "COPY .streamlit/config.toml .streamlit/config.toml" in dockerfile
