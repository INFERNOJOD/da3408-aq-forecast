"""A cached, failure-tolerant view of the model registry for the backend.

Forecasts must not fail because the registry is slow, so lookups are cached for
a short time and a registry error returns "unknown" instead of raising.
"""

import threading
import time
from collections.abc import Callable
from datetime import datetime

from src.common.errors import RegistryError
from src.common.logging_setup import get_logger
from src.pipeline.registry import ModelRegistryClient

log = get_logger(__name__)

CACHE_SECONDS = 30


def _num(value: str | None) -> float | None:
    """Parse a tag that holds a number; None if absent or not a number."""
    try:
        return round(float(value), 3) if value is not None else None
    except ValueError:
        return None


class RegistryView:
    """Registry versions for the API, with a small time-based cache."""

    def __init__(
        self,
        registry: ModelRegistryClient,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        """Wrap ``registry``; ``now`` is injectable for tests."""
        self.registry = registry
        self._now = now
        self._lock = threading.Lock()
        self._cached: list[dict] | None = None
        self._at = 0.0

    def invalidate(self) -> None:
        """Drop the cache (after a rollback)."""
        with self._lock:
            self._cached = None

    def versions(self) -> list[dict]:
        """Registry versions newest first, or the last known list on an error."""
        with self._lock:
            if self._cached is not None and self._now() - self._at < CACHE_SECONDS:
                return self._cached
            try:
                self._cached = self.registry.versions()
                self._at = self._now()
            except Exception as exc:  # noqa: BLE001 - any registry error is non-fatal
                log.warning("Registry unavailable: %s", exc)
                self._cached = self._cached or []
                self._at = self._now()
            return self._cached

    def info(self, version: str | None) -> dict:
        """Name, version, run id and commit of a version (None values if unknown)."""
        match = next((v for v in self.versions() if v["version"] == version), None)
        tags = match["tags"] if match else {}
        return {
            "name": self.registry.name,
            "version": version,
            "mlflow_run_id": match["mlflow_run_id"] if match else None,
            "git_commit": (tags.get("git_commit") or "")[:7] or None,
        }

    def champion_version(self) -> str | None:
        """Version carrying the champion alias, as last seen."""
        return next(
            (v["version"] for v in self.versions() if "champion" in v["aliases"]),
            None,
        )

    def champion_mae_1h(self) -> float | None:
        """Return the champion's 1 h MAE on its evaluation window (tag ``mae_1h``)."""
        version = self.champion_version()
        match = next((v for v in self.versions() if v["version"] == version), None)
        return _num(match["tags"].get("mae_1h")) if match else None

    def models(self) -> list[dict]:
        """Return the body of GET /pipeline/models."""
        out = []
        for v in self.versions():
            tags = v["tags"]
            created = (
                datetime.fromtimestamp(v["created_ms"] / 1000).isoformat(
                    timespec="seconds"
                )
                if v.get("created_ms")
                else None
            )
            out.append(
                {
                    "version": v["version"],
                    "aliases": v["aliases"],
                    "mlflow_run_id": v["mlflow_run_id"],
                    "created_at": created,
                    "cutoff": tags.get("cutoff"),
                    "mae_1h": _num(tags.get("mae_1h")),
                    "mae_24h": _num(tags.get("mae_24h")),
                    "git_commit": (tags.get("git_commit") or "")[:7] or None,
                }
            )
        return out

    def rollback(self, version: str | None) -> tuple[str | None, str]:
        """Move the champion alias. RegistryError means a 400 for the caller."""
        try:
            return self.registry.rollback(version)
        finally:
            self.invalidate()


__all__ = ["RegistryError", "RegistryView"]
