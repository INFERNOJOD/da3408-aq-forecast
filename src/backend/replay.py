"""The replay clock: simulated "now" for the 2020 lockdown replay.

The clock does not run a thread. It stores where the replay was when it last
changed state and works out the current hour from the wall clock when asked.
That keeps it simple to test (pass a fake ``now`` function) and means a stopped
backend can never leave a thread running.
"""

import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from src.backend.errors import ApiError

MIN_SPEED, MAX_SPEED = 0.1, 20.0


class ReplayClock:
    """Simulated time that moves ``speed_hps`` replay hours per real second."""

    def __init__(
        self,
        start: datetime,
        end: datetime,
        default_speed: float,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a stopped clock sitting at ``start``."""
        self.start, self.end = start, end
        self.default_speed = default_speed
        self._now = now
        self._lock = threading.Lock()
        self._running = False
        self._speed = default_speed
        self._base_hours = 0.0  # replay hours elapsed when state last changed
        self._since = 0.0  # value of now() when state last changed

    def _hours(self) -> float:
        """Replay hours elapsed, capped at the length of the replay."""
        total = (self.end - self.start).total_seconds() / 3600
        elapsed = self._base_hours
        if self._running:
            elapsed += (self._now() - self._since) * self._speed
        return min(elapsed, total)

    def _settle(self) -> None:
        """Stop the clock if it ran past the end. Call with the lock held."""
        if self._running and self._hours() >= (
            (self.end - self.start).total_seconds() / 3600
        ):
            self._base_hours = self._hours()
            self._running = False

    @property
    def sim_time(self) -> datetime:
        """The current replay hour (whole hours)."""
        with self._lock:
            self._settle()
            return self.start + timedelta(hours=int(self._hours()))

    @property
    def replay_hour(self) -> int:
        """Whole replay hours elapsed since the start."""
        with self._lock:
            self._settle()
            return int(self._hours())

    @property
    def running(self) -> bool:
        """True while the clock advances."""
        with self._lock:
            self._settle()
            return self._running

    def state(self) -> dict:
        """Return the body of GET/POST /ops/replay."""
        with self._lock:
            self._settle()
            current = self.start + timedelta(hours=int(self._hours()))
            return {
                "running": self._running,
                "sim_time": current.isoformat(timespec="seconds"),
                "speed_hps": self._speed,
                "start": self.start.isoformat(timespec="seconds"),
                "end": self.end.isoformat(timespec="seconds"),
            }

    def apply(self, action: str, speed: float | None = None) -> dict:
        """Run ``start``, ``stop`` or ``reset``. Raises ApiError 409 on a no-op."""
        with self._lock:
            self._settle()
            if action == "start":
                if self._running:
                    raise ApiError(409, "CONFLICT", "Replay is already running.")
                self._speed = speed or self.default_speed
                self._base_hours = self._hours()
                self._since = self._now()
                self._running = True
            elif action == "stop":
                if not self._running:
                    raise ApiError(409, "CONFLICT", "Replay is not running.")
                self._base_hours = self._hours()
                self._running = False
            else:  # reset
                self._running = False
                self._base_hours = 0.0
                if speed:
                    self._speed = speed
        return self.state()
