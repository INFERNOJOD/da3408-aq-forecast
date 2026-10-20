"""HTTP client for the model server (docs/LLD.md section 4)."""

import requests

from src.common.errors import AQError
from src.common.logging_setup import get_logger
from src.common.schema import FEATURES

log = get_logger(__name__)

TIMEOUT_S = 10


class ModelUnavailableError(AQError):
    """The model server is down, slow or returned something unusable."""


class ModelServerClient:
    """Sends feature rows to ``POST /invocations`` and returns the predictions."""

    def __init__(self, base_url: str) -> None:
        """Remember the server address (without a trailing slash)."""
        self.base_url = base_url.rstrip("/")

    def is_up(self) -> bool:
        """Return True if ``GET /ping`` answers 200."""
        try:
            return requests.get(f"{self.base_url}/ping", timeout=3).status_code == 200
        except requests.RequestException:
            return False

    def predict(self, rows: list[dict]) -> list[dict]:
        """Return ``[{"pm25": ..., "model_version": ...}]`` in the order sent."""
        body = {
            "dataframe_split": {
                "columns": FEATURES,
                "data": [[row[c] for c in FEATURES] for row in rows],
            }
        }
        try:
            resp = requests.post(
                f"{self.base_url}/invocations", json=body, timeout=TIMEOUT_S
            )
        except requests.RequestException as exc:
            raise ModelUnavailableError(f"Model server unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise ModelUnavailableError(f"Model server answered {resp.status_code}")
        try:
            preds = resp.json()["predictions"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ModelUnavailableError(
                "Model server sent an unreadable answer"
            ) from exc
        if len(preds) != len(rows):
            raise ModelUnavailableError(
                "Model server returned the wrong number of rows"
            )
        return preds
