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


class EpisodeGate:
    """Allows one drift-triggered retrain per drift episode.

    An episode starts with the retrain that a drift alert causes. It ends only
    after the drift rule has been false for ``clear_hours`` simulated hours in a
    row. Until then further drift alerts are ignored. The state is a small JSON
    file, so a backend restart does not open a second retrain for the same
    episode. Times are replay (simulated) times, because the rule follows the
    replay clock and not the wall clock.
    """

    def __init__(self, directory: Path, clear_hours: int) -> None:
        """Keep the state in ``directory/episode.json``."""
        self.path = Path(directory) / "episode.json"
        self.clear = timedelta(hours=clear_hours)
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"open": False, "clear_since": None}

    def _save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state), encoding="utf-8")

    def is_open(self) -> bool:
        """Return True while a retrain for the current episode has been made."""
        return bool(self._load()["open"])

    def open_episode(self) -> None:
        """Record that a drift alert has just caused a retrain."""
        with self._lock:
            self._save({"open": True, "clear_since": None})

    def observe(self, drift_now: bool, sim_time: datetime) -> None:
        """Feed the drift rule's value at ``sim_time``; closes the episode."""
        with self._lock:
            state = self._load()
            if not state["open"]:
                return
            since = state["clear_since"]
            since = datetime.fromisoformat(since) if since else None
            if drift_now:
                new = {"open": True, "clear_since": None}
            elif since is None or sim_time < since:  # first quiet hour, or replay reset
                new = {"open": True, "clear_since": sim_time.isoformat()}
            elif sim_time - since >= self.clear:
                log.info("Drift episode closed: rule false since %s", since)
                new = {"open": False, "clear_since": None}
            else:
                return
            self._save(new)


class RetrainQueue:
    """Creates and inspects retrain request files."""

    def __init__(
        self,
        directory: Path,
        cooldown_min: int,
        now: Callable[[], datetime] = datetime.now,
        episode: EpisodeGate | None = None,
    ) -> None:
        """Use ``directory/requests`` for the files."""
        self.episode = episode
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

    def create(
        self,
        reason: str,
        cutoff: str,
        trigger: str = "manual",
        drift: dict | None = None,
    ) -> dict:
        """Write a new request. Raises ApiError 409 if one is already active.

        ``trigger`` becomes the pipeline's ``PIPELINE_TRIGGER``. ``drift`` holds
        the drift numbers at the time of an alert; the runner hands them to the
        train stage, which logs them as ``drift_*`` metrics.
        """
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
                "trigger": trigger,
                "drift": drift or {},
            }
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.dir / f"{record['request_id']}.json"
            path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            log.info("Retrain request %s created (%s)", record["request_id"], reason)
            return record

    def from_alerts(
        self,
        alerts: list[dict],
        cutoff: str,
        drift: Callable[[], dict] = dict,
    ) -> bool:
        """Create a request for a firing alert with ``action=retrain``.

        Returns False if there is none, or the open drift episode, the cooldown
        or an active request stops it. Every alert is logged either way.
        """
        wanted = None
        for alert in alerts:
            labels = alert.get("labels", {})
            log.info("Alert %s: %s", alert.get("status"), labels)
            if alert.get("status") == "firing" and labels.get("action") == "retrain":
                wanted = wanted or labels.get("alertname", "unknown")
        if wanted is None:
            return False
        if self.episode and self.episode.is_open():
            log.info("Retrain alert ignored: this drift episode was already retrained")
            return False
        if self.in_cooldown():
            log.info("Retrain alert ignored: cooldown")
            return False
        try:
            self.create(f"drift_alert:{wanted}", cutoff, "drift_alert", drift())
        except ApiError:
            log.info("Retrain alert ignored: a request is already active")
            return False
        if self.episode:
            self.episode.open_episode()
        return True
