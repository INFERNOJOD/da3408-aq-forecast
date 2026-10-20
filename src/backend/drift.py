"""Live drift report for GET /ops/drift and the drift gauges.

The PSI part uses ``src.monitoring.drift.DriftDetector``, the same code the
features stage used for the thresholds and ``scripts/replay.py`` uses for the
acceptance test. It needs only the stored features, so drift is still detected
when the model server is down.

The rolling MAE ratio needs the champion's 1 h forecasts for the last 72
replayed hours, so it asks the model server for them in one call. It is
reported and exported, but it is not part of the drift rule (docs/HLD.md).
Results are cached per replay hour and champion version, because Prometheus
asks every 15 seconds and the answer only changes when the clock moves.
"""

import json
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from src.backend.model_client import ModelServerClient, ModelUnavailableError
from src.backend.registry_view import RegistryView
from src.backend.replay import ReplayClock
from src.backend.store import ServingStore
from src.common.logging_setup import get_logger
from src.common.schema import FEATURE_COLUMNS
from src.monitoring.drift import DriftDetector

log = get_logger(__name__)

WINDOW_H = 168
MAE_WINDOW_H = 72
MIN_MAE_HOURS = 24  # the MAE ratios stay null until this many replay hours exist
TARGET_1H = "y_1h"


def _num(value) -> float | None:
    """Float or None for NaN/None, so the value can go into JSON."""
    return None if value is None or pd.isna(value) else float(value)


class DriftReport:
    """Builds the drift report from the replay clock, the store and the model."""

    def __init__(
        self,
        cities: tuple[str, ...],
        clock: ReplayClock,
        reports_dir: Path,
        min_cities: int,
        mae_ratio: float,
        store: ServingStore,
        client: ModelServerClient,
        registry: RegistryView,
    ) -> None:
        """Keep the collaborators; the reference files are read lazily."""
        self.cities, self.clock = cities, clock
        self.reports_dir = Path(reports_dir)
        self.min_cities, self.mae_ratio = min_cities, mae_ratio
        self.store, self.client, self.registry = store, client, registry
        self._lock = threading.Lock()
        self._files: dict[str, tuple[float, dict]] = {}
        self._mae_cache: tuple[tuple, dict] | None = None

    def _read(self, name: str) -> dict:
        """Read a JSON file of reports_dir again only if it changed; {} if absent."""
        path = self.reports_dir / name
        try:
            mtime = path.stat().st_mtime
            cached = self._files.get(name)
            if cached and cached[0] == mtime:
                return cached[1]
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        self._files[name] = (mtime, doc)
        return doc

    def detector(self) -> DriftDetector:
        """Build a detector from the current reference and threshold files."""
        baseline = self._read("baseline_stats.json").get("cities", {})
        thresholds = self._read("drift_thresholds.json").get("cities", {})
        return DriftDetector(
            {c: v.get("weeks", []) for c, v in baseline.items()},
            {c: v["psi_threshold"] for c, v in thresholds.items()},
            self.min_cities,
            WINDOW_H,
        )

    def _mae_ratios(self, sim: pd.Timestamp, hour: int) -> dict[str, float | None]:
        """1 h MAE over the last 72 replayed hours / champion's eval MAE, per city.

        Key ``"pooled"`` holds all cities together. Every value is None while
        fewer than 24 replay hours exist, or when the model server or the
        champion's MAE is not available.
        """
        none = {c: None for c in [*self.cities, "pooled"]}
        version = self.registry.champion_version()
        denominator = self.registry.champion_mae_1h()
        if hour < MIN_MAE_HOURS or not denominator:
            return none
        key = (hour, version)
        if self._mae_cache and self._mae_cache[0] == key:
            return self._mae_cache[1]
        # Forecasts issued at t <= sim - 1 are for t + 1 <= sim, so their actual
        # value is already known at the current replay hour.
        first = max(
            sim - pd.Timedelta(hours=MAE_WINDOW_H), pd.Timestamp(self.clock.start)
        )
        frames = []
        for city in self.cities:
            rows = self.store.window(city, first, sim - pd.Timedelta(hours=1))
            if TARGET_1H not in rows:
                return none
            rows = rows[rows[TARGET_1H].notna() & rows["city_code"].notna()]
            frames.append(rows.assign(City=city))
        rows = pd.concat(frames)
        if rows.empty:
            return none
        payload = [
            {"horizon_h": 1, **{c: _num(r[c]) for c in FEATURE_COLUMNS}}
            for _, r in rows.iterrows()
        ]
        try:
            preds = self.client.predict(payload)
        except ModelUnavailableError as exc:
            log.warning("MAE ratio not computed: %s", exc)
            return none
        err = np.abs(np.array([float(p["pm25"]) for p in preds]) - rows[TARGET_1H])
        rows = rows.assign(err=err.to_numpy())
        out = {
            c: round(float(g["err"].mean()) / denominator, 4)
            for c, g in rows.groupby("City")
        }
        out = {c: out.get(c) for c in self.cities}
        out["pooled"] = round(float(rows["err"].mean()) / denominator, 4)
        self._mae_cache = (key, out)
        return out

    def report(self) -> dict:
        """Return the body of GET /ops/drift."""
        with self._lock:
            hour = self.clock.replay_hour
            sim = pd.Timestamp(self.clock.sim_time)
            start = sim - pd.Timedelta(hours=WINDOW_H - 1)
            windows = {
                c: self.store.window(c, start, sim)["pm25_lag_1"].to_numpy(dtype=float)
                for c in self.cities
            }
            rule = self.detector().evaluate(windows, hour)
            ratios = self._mae_ratios(sim, hour)
        cities = [
            {**row, "mae_ratio_1h": ratios.get(row["city"])} for row in rule["cities"]
        ]
        pooled = ratios["pooled"]
        return {
            "sim_time": sim.isoformat(),
            "window_h": WINDOW_H,
            "reference_block": rule["reference_block"],
            "min_cities": self.min_cities,
            "mae_ratio_threshold": self.mae_ratio,
            "cities": cities,
            "cities_exceeding": rule["cities_exceeding"],
            "mae_ratio_pooled": pooled,
            "psi_condition": rule["psi_condition"],
            "mae_condition": pooled is not None and pooled > self.mae_ratio,
            "any_drift": rule["any_drift"],
        }

    def summary(self) -> dict:
        """Flat numbers for a retrain request (logged as ``drift_*`` in MLflow)."""
        report = self.report()
        psis = [c["psi"] for c in report["cities"] if c["psi"] is not None]
        out = {
            "cities_exceeding": report["cities_exceeding"],
            "psi_max": max(psis) if psis else None,
            "mae_ratio_pooled": report["mae_ratio_pooled"],
        }
        return {k: v for k, v in out.items() if v is not None}
