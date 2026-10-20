"""Tests for the model-server proxy and the champion watcher (no real MLflow)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import requests
from prometheus_client import REGISTRY
from src.model_server import supervisor
from src.model_server.proxy import Upstream, count_rows, make_handler
from src.model_server.supervisor import ModelServerError, ModelSupervisor


def split_body(horizons):
    """A dataframe_split body with the given horizon per row."""
    cols = ["horizon_h", "city_code"]
    return json.dumps(
        {"dataframe_split": {"columns": cols, "data": [[h, 0] for h in horizons]}}
    ).encode()


def sample(name, **labels):
    """Current value of a Prometheus sample (0 if it does not exist yet)."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


class FakeMlflow(BaseHTTPRequestHandler):
    """Stands in for ``mlflow models serve``."""

    def log_message(self, *args):
        pass

    def _send(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, b"{}")

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/boom":
            self._send(400, b'{"error_code": "BAD_REQUEST"}')
        else:
            self._send(200, b'{"predictions": [{"pm25": 1.0}]}')


@pytest.fixture
def proxy():
    """A proxy in front of a fake MLflow; yields (proxy_url, upstream)."""
    fake = HTTPServer(("127.0.0.1", 0), FakeMlflow)
    upstream = Upstream()
    front = HTTPServer(("127.0.0.1", 0), make_handler(upstream))
    for server in (fake, front):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    upstream.switch(f"http://127.0.0.1:{fake.server_port}", 7)
    yield f"http://127.0.0.1:{front.server_port}", upstream
    fake.shutdown()
    front.shutdown()


def test_count_rows_split_and_records():
    assert count_rows(split_body([1, 24, 1])) == {"1": 2, "24": 1}
    records = json.dumps({"dataframe_records": [{"horizon_h": 24}]}).encode()
    assert count_rows(records) == {"24": 1}


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b'{"inputs": [1]}'])
def test_count_rows_ignores_unreadable_bodies(body):
    assert count_rows(body) == {}


def test_proxy_forwards_and_counts(proxy):
    url, _ = proxy
    before = sample("aq_model_predictions_total", horizon_h="24")
    calls = sample("aq_model_predict_duration_seconds_count")
    resp = requests.post(f"{url}/invocations", data=split_body([24, 24]), timeout=5)
    assert resp.status_code == 200 and resp.json()["predictions"][0]["pm25"] == 1.0
    assert sample("aq_model_predictions_total", horizon_h="24") == before + 2
    assert sample("aq_model_predict_duration_seconds_count") == calls + 1
    assert sample("aq_model_loaded_version") == 7


def test_proxy_passes_errors_through_without_counting(proxy):
    url, _ = proxy
    before = sample("aq_model_predictions_total", horizon_h="1")
    resp = requests.post(f"{url}/boom", data=split_body([1]), timeout=5)
    assert resp.status_code == 400
    assert sample("aq_model_predictions_total", horizon_h="1") == before


def test_ping_is_forwarded(proxy):
    assert requests.get(f"{proxy[0]}/ping", timeout=5).status_code == 200


def test_proxy_answers_503_when_nothing_is_loaded_or_upstream_is_down(proxy):
    url, upstream = proxy
    upstream.switch("http://127.0.0.1:1", 7)  # nothing listens there
    assert requests.get(f"{url}/ping", timeout=5).status_code == 503
    empty = HTTPServer(("127.0.0.1", 0), make_handler(Upstream()))
    threading.Thread(target=empty.serve_forever, daemon=True).start()
    resp = requests.get(f"http://127.0.0.1:{empty.server_port}/ping", timeout=5)
    empty.shutdown()
    assert resp.status_code == 503


class FakeRegistry:
    """Just the two members the supervisor uses."""

    name = "aq-test"

    def __init__(self, champion):
        self.champion = champion

    def champion_version(self):
        return self.champion


class FakeProc:
    """A stand-in for subprocess.Popen."""

    returncode = None

    def __init__(self):
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True

    def wait(self, timeout=None):
        pass


@pytest.fixture
def fake_mlflow(monkeypatch):
    """Replace download, start and readiness checks; record what was started."""
    started = []
    monkeypatch.setattr(supervisor, "download_package", lambda r, v, d: Path(f"/p/{v}"))

    def start(model_dir, port, version):
        proc = FakeProc()
        started.append((version, port, proc))
        return proc

    monkeypatch.setattr(supervisor, "start_mlflow", start)
    monkeypatch.setattr(supervisor, "wait_ready", lambda proc, port, t: None)
    return started


def test_sync_loads_then_swaps_on_a_new_champion(tmp_path, fake_mlflow):
    registry, upstream = FakeRegistry("1"), Upstream()
    sup = ModelSupervisor(registry, upstream, tmp_path)
    assert sup.sync() is True and sup.version == "1"
    assert sup.sync() is False  # nothing changed
    registry.champion = "2"
    assert sup.sync() is True and sup.version == "2"
    (v1, port1, proc1), (v2, port2, proc2) = fake_mlflow
    assert port1 != port2  # the new model uses the spare port
    assert proc1.stopped and not proc2.stopped  # the old one stops after the switch
    assert upstream.url == f"http://127.0.0.1:{port2}"
    registry.champion = "1"  # a rollback is just another change
    assert sup.sync() is True and sup.version == "1"


def test_sync_without_a_champion_does_nothing(tmp_path, fake_mlflow):
    sup = ModelSupervisor(FakeRegistry(None), Upstream(), tmp_path)
    assert sup.sync() is False and fake_mlflow == []


def test_failed_load_keeps_the_old_model(tmp_path, fake_mlflow, monkeypatch):
    registry, upstream = FakeRegistry("1"), Upstream()
    sup = ModelSupervisor(registry, upstream, tmp_path)
    sup.sync()
    old_url = upstream.url

    def fail(proc, port, timeout):
        raise ModelServerError("did not start")

    monkeypatch.setattr(supervisor, "wait_ready", fail)
    registry.champion = "2"
    assert sup.sync() is False
    assert sup.version == "1" and upstream.url == old_url
    assert fake_mlflow[-1][2].stopped  # the failed process was cleaned up
    assert not fake_mlflow[0][2].stopped  # the old one still serves


def test_wait_ready_reports_a_process_that_exited():
    proc = FakeProc()
    proc.stopped, proc.returncode = True, 3
    with pytest.raises(ModelServerError, match="code 3"):
        supervisor.wait_ready(proc, 1, 5)
