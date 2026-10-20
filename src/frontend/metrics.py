"""Prometheus metrics of the frontend (docs/LLD.md section 5).

Streamlit re-runs the page script on every interaction, so the metric objects
are created once, at import time, and the HTTP exporter is started once per
process (``start_exporter`` is safe to call on every run).
"""

import os
import threading

from prometheus_client import Counter, Histogram, start_http_server

from src.common.logging_setup import get_logger

log = get_logger(__name__)

page_views = Counter("aq_ui_page_views_total", "Page renders.", ["page"])
backend_duration = Histogram(
    "aq_ui_backend_call_duration_seconds",
    "Time for a call from the frontend to the backend.",
    ["endpoint"],
)
backend_errors = Counter(
    "aq_ui_backend_errors_total", "Failed calls to the backend.", ["endpoint"]
)

_started = False
_lock = threading.Lock()


def start_exporter() -> None:
    """Serve ``/metrics`` on ``UI_METRICS_PORT`` (8502) the first time only."""
    global _started  # noqa: PLW0603 - one exporter per process
    with _lock:
        if _started:
            return
        port = int(os.environ.get("UI_METRICS_PORT", "8502"))
        try:
            start_http_server(port)
            log.info("Frontend metrics on port %d", port)
        except OSError as exc:
            log.warning("Frontend metrics not started on port %d: %s", port, exc)
        _started = True
