"""Stage 15 checks: TLS certificates, HTTPS wiring, non-root containers, secrets.

The 401-without-key cases live in test_backend.py (``test_ops_requires_key``).
"""

import os
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml
from src.backend import main as backend_main
from src.frontend.client import BackendClient, BackendError

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]

needs_openssl = pytest.mark.skipif(not shutil.which("openssl"), reason="no openssl")


def load(rel):
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    """Run scripts/make_certs.sh into a temporary folder."""
    out = tmp_path_factory.mktemp("certs")
    subprocess.run(
        [str(ROOT / "scripts" / "make_certs.sh"), "10.0.0.5", "aq.local"],
        env={**os.environ, "CERT_DIR": str(out)},
        check=True,
        capture_output=True,
    )
    return out


# ---- certificates ---------------------------------------------------------


@needs_openssl
def test_make_certs_signs_server_cert_with_ca(certs):
    ok = subprocess.run(
        ["openssl", "verify", "-CAfile", certs / "ca.crt", certs / "server.crt"],
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stderr
    text = subprocess.run(
        ["openssl", "x509", "-in", certs / "server.crt", "-noout", "-ext",
         "subjectAltName"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    for name in ["DNS:localhost", "DNS:backend", "DNS:frontend", "IP Address:127.0.0.1",
                 "IP Address:10.0.0.5", "DNS:aq.local"]:  # fmt: skip
        assert name in text


@needs_openssl
def test_private_keys_are_owner_only(certs):
    for key in ["ca.key", "server.key"]:
        assert (certs / key).stat().st_mode & 0o077 == 0


def test_certs_and_env_are_gitignored():
    out = subprocess.run(
        ["git", "check-ignore", "certs/server.key", "certs/ca.key", ".env"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert out == ["certs/server.key", "certs/ca.key", ".env"]


# ---- the frontend client over real TLS ------------------------------------


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server naming)
        body = b'{"cities": ["Delhi"]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def https_url(certs):
    """A tiny HTTPS server using the generated server certificate."""
    server = HTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certs / "server.crt", certs / "server.key")
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"https://localhost:{server.server_address[1]}"
    server.shutdown()


@needs_openssl
def test_client_trusts_backend_with_ca_file(https_url, certs):
    client = BackendClient(https_url, verify=str(certs / "ca.crt"))
    assert client.get("/cities") == {"cities": ["Delhi"]}


@needs_openssl
def test_client_without_ca_gives_plain_message_not_ssl_trace(https_url):
    # The system CAs do not know my CA, so the check fails. The user must see
    # the same friendly "does not answer" message as for a backend that is down.
    client = BackendClient(https_url, verify=True)
    with pytest.raises(BackendError) as err:
        client.get("/cities")
    assert err.value.code == "UNREACHABLE"
    assert "SSL" not in str(err.value) and "certificate" not in str(err.value)


# ---- backend start-up -----------------------------------------------------


def start_backend(monkeypatch, cert, key):
    seen = {}
    monkeypatch.setenv("TLS_CERT_FILE", str(cert))
    monkeypatch.setenv("TLS_KEY_FILE", str(key))
    monkeypatch.setattr(backend_main, "load_env", lambda: None)
    monkeypatch.setattr(backend_main.Settings, "from_env", classmethod(lambda c: None))
    monkeypatch.setattr(backend_main, "create_app", lambda s: "app")
    monkeypatch.setattr(backend_main.uvicorn, "run", lambda app, **kw: seen.update(kw))
    backend_main.main()
    return seen


def test_backend_serves_https_when_cert_exists(monkeypatch, tmp_path):
    cert, key = tmp_path / "s.crt", tmp_path / "s.key"
    cert.write_text("c")
    key.write_text("k")
    seen = start_backend(monkeypatch, cert, key)
    assert seen["ssl_certfile"] == str(cert) and seen["ssl_keyfile"] == str(key)


def test_backend_falls_back_to_http_without_cert(monkeypatch, tmp_path):
    seen = start_backend(monkeypatch, tmp_path / "none.crt", tmp_path / "none.key")
    assert "ssl_certfile" not in seen


# ---- compose and monitoring wiring ----------------------------------------


def test_browser_traffic_goes_through_tls_proxy():
    proxy = SERVICES["tls-proxy"]
    assert "443:8443" in proxy["ports"] and "8501:8080" in proxy["ports"]
    assert "ports" not in SERVICES["frontend"]  # only reachable via the proxy
    caddy = (ROOT / "docker/tls_proxy/Caddyfile").read_text(encoding="utf-8")
    assert "tls /certs/server.crt /certs/server.key" in caddy
    assert "redir https://{host}{uri}" in caddy


def test_backend_and_its_clients_use_https():
    backend = SERVICES["backend"]
    assert backend["environment"]["TLS_CERT_FILE"] == "/certs/server.crt"
    assert "https://localhost:8000/health" in backend["healthcheck"]["test"]
    front = SERVICES["frontend"]["environment"]
    assert front["BACKEND_URL"].startswith("https://")
    assert front["BACKEND_CA_FILE"] == "/certs/ca.crt"
    job = next(j for j in load("monitoring/prometheus.yml")["scrape_configs"]
               if j["job_name"] == "backend")  # fmt: skip
    assert job["scheme"] == "https" and job["tls_config"]["ca_file"]
    hook = load("monitoring/alertmanager.yml")["receivers"][0]["webhook_configs"][0]
    assert hook["url"].startswith("https://backend:8000/")
    assert hook["http_config"]["tls_config"]["ca_file"]


# Third-party images I checked with `docker image inspect` (Config.User).
NON_ROOT_IMAGES = {"prom/", "grafana/"}


def test_every_container_runs_as_non_root():
    for name, svc in SERVICES.items():
        if "user" in svc:
            assert not str(svc["user"]).startswith("0"), name
        elif "build" in svc:
            dockerfile = (ROOT / svc["build"]["dockerfile"]).read_text(encoding="utf-8")
            users = [ln.split()[1] for ln in dockerfile.splitlines()
                     if ln.startswith("USER ")]  # fmt: skip
            assert users and users[-1] != "root", name
        else:
            assert any(svc["image"].startswith(p) for p in NON_ROOT_IMAGES), name


def test_secrets_come_only_from_env_file():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "${OPS_API_KEY:?" in text and "${GRAFANA_ADMIN_PASSWORD:?" in text
    for svc in SERVICES.values():
        for key, value in (svc.get("environment") or {}).items():
            if key.endswith(("API_KEY", "PASSWORD")):
                assert str(value).startswith("${"), key
        for vol in svc.get("volumes", []):
            assert "secrets" not in vol  # no secret files beside .env
