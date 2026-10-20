"""The frontend's only door to the rest of the system: the backend REST API.

``BackendClient`` knows the endpoints of docs/LLD.md and nothing else. The base
URL comes from ``BACKEND_URL``. Every call is timed, and failures are counted,
so Prometheus can see how the backend looks from the user's side.
"""

import os
import re

import requests

from src.common.errors import AQError
from src.common.logging_setup import get_logger
from src.frontend import metrics

log = get_logger(__name__)

TIMEOUT_S = 15


class BackendError(AQError):
    """A call failed. ``code`` is the LLD error code, or a local one.

    Local codes: ``UNREACHABLE`` (no answer) and ``BAD_RESPONSE`` (not JSON).
    """

    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        """Keep the code and the HTTP status (None when there was no answer)."""
        super().__init__(message)
        self.code, self.status = code, status


def endpoint_label(path: str) -> str:
    """Return a path without ids, so the metric label has few values."""
    return re.sub(r"\?.*$", "", path)


class BackendClient:
    """Calls the backend. ``api_key`` is sent only to ``/ops/*`` paths."""

    def __init__(
        self,
        base_url: str | None = None,
        verify: str | bool | None = None,
        session: requests.Session | None = None,
    ) -> None:
        """Read ``BACKEND_URL`` and ``BACKEND_CA_FILE`` (a self-signed CA) if unset."""
        url = base_url or os.environ.get("BACKEND_URL", "http://localhost:8000")
        self.base_url = url.rstrip("/")
        ca_file = os.environ.get("BACKEND_CA_FILE")
        self.verify = verify if verify is not None else (ca_file or True)
        self.session = session or requests.Session()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        body: dict | None = None,
        api_key: str | None = None,
    ) -> dict:
        """Return the JSON body. Raises BackendError for any failure."""
        label = endpoint_label(path)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            with metrics.backend_duration.labels(label).time():
                resp = self.session.request(
                    method,
                    f"{self.base_url}{path}",
                    params=params,
                    json=body,
                    headers=headers,
                    timeout=TIMEOUT_S,
                    verify=self.verify,
                )
        except requests.RequestException as exc:
            metrics.backend_errors.labels(label).inc()
            log.warning("Backend unreachable on %s: %s", label, exc)
            raise BackendError("UNREACHABLE", "The backend does not answer.") from exc
        try:
            data = resp.json()
        except ValueError as exc:
            metrics.backend_errors.labels(label).inc()
            raise BackendError(
                "BAD_RESPONSE",
                "The backend sent an unreadable answer.",
                resp.status_code,
            ) from exc
        if resp.status_code >= 400:
            metrics.backend_errors.labels(label).inc()
            err = data.get("error", {}) if isinstance(data, dict) else {}
            raise BackendError(
                err.get("code", "ERROR"),
                err.get("message", f"HTTP {resp.status_code}"),
                resp.status_code,
            )
        return data

    def get(self, path: str, **kwargs) -> dict:
        """GET ``path``."""
        return self.request("GET", path, **kwargs)

    def post(self, path: str, body: dict, **kwargs) -> dict:
        """POST ``body`` as JSON to ``path``."""
        return self.request("POST", path, body=body, **kwargs)
