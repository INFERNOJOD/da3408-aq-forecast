"""Drift report for GET /ops/drift.

Stage 10 only returns the shape of the report. The PSI and MAE-ratio numbers
come with the drift module in Stage 11, so every score is None here and
``any_drift`` is always false. The cities and the replay block are real.
"""

import json
from pathlib import Path

from src.backend.replay import ReplayClock

WINDOW_H = 168
LAST_BLOCK = 13  # reports/baseline_stats.json has 14 blocks (0..13)


class DriftReport:
    """Builds the drift report from the replay clock and the saved thresholds."""

    def __init__(
        self,
        cities: tuple[str, ...],
        clock: ReplayClock,
        reports_dir: Path,
        min_cities: int,
        mae_ratio: float,
    ) -> None:
        """Keep the settings; thresholds are read on each call."""
        self.cities, self.clock = cities, clock
        self.reports_dir = Path(reports_dir)
        self.min_cities, self.mae_ratio = min_cities, mae_ratio

    def _thresholds(self) -> dict:
        """Per-city PSI thresholds, or {} until Stage 11 writes the file."""
        try:
            path = self.reports_dir / "drift_thresholds.json"
            return json.loads(path.read_text(encoding="utf-8")).get("cities", {})
        except (OSError, ValueError):
            return {}

    def report(self) -> dict:
        """Return the body of GET /ops/drift."""
        thresholds = self._thresholds()
        cities = []
        for city in self.cities:
            threshold = thresholds.get(city, {}).get("psi_threshold")
            cities.append(
                {
                    "city": city,
                    "psi": None,
                    "psi_threshold": threshold,
                    "exceeds": None,
                    "votes": False,
                    "mae_ratio_1h": None,
                }
            )
        return {
            "sim_time": self.clock.state()["sim_time"],
            "window_h": WINDOW_H,
            "reference_block": min(self.clock.replay_hour // WINDOW_H, LAST_BLOCK),
            "min_cities": self.min_cities,
            "mae_ratio_threshold": self.mae_ratio,
            "cities": cities,
            "cities_exceeding": 0,
            "mae_ratio_pooled": None,
            "psi_condition": False,
            "mae_condition": False,
            "any_drift": False,
        }
