"""A small reverse proxy in front of ``mlflow models serve``.

``mlflow models serve`` has no Prometheus endpoint, and the course asks for
metrics on every component. I put this proxy on the public port (5001) and
forward every request to the MLflow process on an internal port. It counts the
rows predicted per horizon and times each call, and it exposes the metrics on a
separate port (8001, see docs/LLD.md section 5).

The upstream can change while the proxy runs (the watcher starts the new model
on a spare port, then calls ``Upstream.switch``), so a promotion causes no
failed requests.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import requests
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from src.common.logging_setup import get_logger

log = get_logger(__name__)

PREDICTIONS = Counter(
    "aq_model_predictions_total", "Rows predicted, by horizon.", ["horizon_h"]
)
DURATION = Histogram(
    "aq_model_predict_duration_seconds",
    "Time MLflow takes to answer /invocations.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
)
LOADED_VERSION = Gauge(
    "aq_model_loaded_version", "Registry version of the model being served."
)
UPSTREAM_TIMEOUT_S = 30


class Upstream:
    """The URL of the MLflow process that currently answers requests."""

    def __init__(self, url: str | None = None) -> None:
        """Start with ``url`` (None means no model is ready yet)."""
        self._url = url
        self._lock = threading.Lock()

    @property
    def url(self) -> str | None:
        """Current upstream URL, or None."""
        with self._lock:
            return self._url

    def switch(self, url: str, version: int | float | str) -> None:
        """Send new requests to ``url`` and record the version in the gauge."""
        with self._lock:
            self._url = url
        LOADED_VERSION.set(float(version))
        log.info("Proxy now forwards to %s (model version %s)", url, version)


def count_rows(body: bytes) -> dict[str, int]:
    """Return rows per horizon in an /invocations body (empty if unreadable).

    Reads the two MLflow input shapes the backend may use, ``dataframe_split``
    and ``dataframe_records``. A body it cannot read is simply not counted.
    """
    try:
        doc = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return {}
    counts: dict[str, int] = {}
    if not isinstance(doc, dict):
        return counts
    split = doc.get("dataframe_split")
    records = doc.get("dataframe_records")
    if isinstance(split, dict) and "horizon_h" in split.get("columns", []):
        idx = split["columns"].index("horizon_h")
        horizons = [row[idx] for row in split.get("data", []) if len(row) > idx]
    elif isinstance(records, list):
        horizons = [r.get("horizon_h") for r in records if isinstance(r, dict)]
    else:
        return counts
    for horizon in horizons:
        key = str(horizon)
        counts[key] = counts.get(key, 0) + 1
    return counts


def make_handler(upstream: Upstream) -> type[BaseHTTPRequestHandler]:
    """Build the request handler class bound to one ``Upstream``."""

    class Handler(BaseHTTPRequestHandler):
        """Forward GET and POST to MLflow, measuring /invocations."""

        def log_message(self, fmt: str, *args: Any) -> None:
            """Send access lines to the logging module at DEBUG level."""
            log.debug("%s " + fmt, self.address_string(), *args)

        def _reply(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _forward(self, method: str, body: bytes | None) -> None:
            base = upstream.url
            if base is None:
                self._reply(503, b'{"error": "no model loaded"}', "application/json")
                return
            headers = {"Content-Type": self.headers.get("Content-Type", "")}
            started = time.perf_counter()
            try:
                resp = requests.request(
                    method,
                    base + self.path,
                    data=body,
                    headers=headers,
                    timeout=UPSTREAM_TIMEOUT_S,
                )
            except requests.RequestException as exc:
                log.error("Upstream %s failed: %s", base, exc)
                self._reply(503, b'{"error": "model unavailable"}', "application/json")
                return
            if self.path.split("?")[0] == "/invocations":
                DURATION.observe(time.perf_counter() - started)
                if resp.status_code == 200 and body:
                    for horizon, n in count_rows(body).items():
                        PREDICTIONS.labels(horizon_h=horizon).inc(n)
            self._reply(
                resp.status_code,
                resp.content,
                resp.headers.get("Content-Type", "application/json"),
            )

        def do_GET(self) -> None:  # noqa: N802 (name fixed by http.server)
            """Forward a GET (for example /ping)."""
            self._forward("GET", None)

        def do_POST(self) -> None:  # noqa: N802 (name fixed by http.server)
            """Forward a POST (for example /invocations)."""
            length = int(self.headers.get("Content-Length") or 0)
            self._forward("POST", self.rfile.read(length))

    return Handler


def start_proxy(
    upstream: Upstream, port: int, metrics_port: int
) -> ThreadingHTTPServer:
    """Start the metrics endpoint and the proxy; the proxy runs in a thread."""
    start_http_server(metrics_port)
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(upstream))  # noqa: S104
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Proxy on :%d, metrics on :%d", port, metrics_port)
    return server
