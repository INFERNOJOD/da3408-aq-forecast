"""Retrain requests: small JSON files that the ops runner picks up.

The backend never runs the pipeline itself. It writes ``ops/requests/<id>.json``
and the runner on the host turns it into ``dvc repro`` (docs/LLD.md section 6).
"""

import json
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from src.backend.errors import ApiError
from src.common.logging_setup import get_logger

log = get_logger(__name__)

ACTIVE = {"queued", "running"}


class RetrainQueue:
    """Creates and inspects retrain request files."""

    def __init__(
        self,
        directory: Path,
        cooldown_min: int,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        """Use ``directory/requests`` for the files."""
        self.dir = Path(directory) / "requests"
        self.cooldown = timedelta(minutes=cooldown_min)
        self._now = now
        self._lock = threading.Lock()

    def _all(self) -> list[dict]:
        """Every readable request file."""
        out = []
        if self.dir.exists():
            for path in sorted(self.dir.glob("*.json")):
                try:
                    out.append(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    log.warning("Unreadable request file %s", path)
        return out

    def has_active(self) -> bool:
        """Return True if a request is queued or running."""
        return any(r.get("status") in ACTIVE for r in self._all())

    def in_cooldown(self) -> bool:
        """Return True if any request was created within the cooldown window."""
        limit = self._now() - self.cooldown
        for rec in self._all():
            try:
                if datetime.fromisoformat(rec["created_at"]) > limit:
                    return True
            except (KeyError, ValueError):
                continue
        return False

    def create(self, reason: str, cutoff: str) -> dict:
        """Write a new request. Raises ApiError 409 if one is already active."""
        with self._lock:
            if self.has_active():
                raise ApiError(
                    409, "CONFLICT", "A retrain is already queued or running."
                )
            now = self._now()
            record = {
                "request_id": f"rt-{now:%Y%m%d-%H%M%S}",
                "reason": reason,
                "cutoff": cutoff,
                "created_at": now.isoformat(timespec="seconds"),
                "status": "queued",
            }
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.dir / f"{record['request_id']}.json"
            path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            log.info("Retrain request %s created (%s)", record["request_id"], reason)
            return record

    def from_alerts(self, alerts: list[dict], cutoff: str) -> bool:
        """Create a request for a firing alert with ``action=retrain``.

        Returns False if there is none, or the cooldown or an active request
        stops it. Every alert is logged either way.
        """
        wanted = None
        for alert in alerts:
            labels = alert.get("labels", {})
            log.info("Alert %s: %s", alert.get("status"), labels)
            if alert.get("status") == "firing" and labels.get("action") == "retrain":
                wanted = wanted or labels.get("alertname", "unknown")
        if wanted is None:
            return False
        if self.in_cooldown():
            log.info("Retrain alert ignored: cooldown")
            return False
        try:
            self.create(f"drift_alert:{wanted}", cutoff)
        except ApiError:
            log.info("Retrain alert ignored: a request is already active")
            return False
        return True
