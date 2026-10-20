"""Tests for the live drift report (src/backend/drift.py)."""

import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from src.backend.drift import DriftReport
from src.backend.model_client import ModelUnavailableError
from src.backend.registry_view import RegistryView
from src.backend.replay import ReplayClock
from src.backend.store import ServingStore
from src.common.schema import FEATURE_COLUMNS

CITIES = ("A", "B", "C")
START = datetime(2020, 3, 25)
REF = {"edges": [10.0, 20.0, 30.0], "proportions": [0.25, 0.25, 0.25, 0.25]}


class Timer:
    """A fake monotonic clock."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Model:
    def __init__(self, value=12.0):
        self.value, self.calls, self.up = value, 0, True

    def predict(self, rows):
        self.calls += 1
        if not self.up:
            raise ModelUnavailableError("down")
        return [{"pm25": self.value, "model_version": "3"} for _ in rows]


class Registry:
    name = "aq-pm25"

    def __init__(self, mae="4.0"):
        tags = {"mae_1h": mae} if mae else {}
        self.rows = [{"version": "3", "aliases": ["champion"], "tags": tags}]

    def versions(self):
        return self.rows


@pytest.fixture
def make(tmp_path):
    """Store from a week before the replay to 300 h after; A is shifted low."""
    hours = pd.date_range("2020-03-18", periods=168 + 300, freq="h")
    frames = []
    for code, city in enumerate(CITIES):
        df = pd.DataFrame({"City": city, "Datetime": hours})
        df["city_code"] = np.int32(code)
        for col in FEATURE_COLUMNS[1:]:
            df[col] = 10.0
        spread = np.tile([5.0, 15.0, 25.0, 35.0], len(hours) // 4)
        df["pm25_lag_1"] = 5.0 if city in ("A", "B") else spread
        df["pm25"] = 10.0
        df["y_1h"] = 10.0
        frames.append(df)
    path = tmp_path / "serving.parquet"
    pd.concat(frames, ignore_index=True).to_parquet(path, index=False)
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "baseline_stats.json").write_text(
        json.dumps({"cities": {c: {"weeks": [REF, REF]} for c in CITIES}})
    )
    (reports / "drift_thresholds.json").write_text(
        json.dumps({"cities": {c: {"psi_threshold": 0.5} for c in ("A", "B", "C")}})
    )

    def _make(min_cities=2, model=None, registry=None):
        timer = Timer()
        clock = ReplayClock(START, datetime(2020, 6, 30, 23), 1.0, now=timer)
        model = model or Model()
        report = DriftReport(
            CITIES, clock, reports, min_cities, 1.5,
            ServingStore(path), model, RegistryView(registry or Registry()),
        )  # fmt: skip
        return report, clock, timer, model

    return _make


def move_to(clock, timer, hour):
    clock.apply("start", 1.0)
    timer.t = hour
    clock.apply("stop")


def test_psi_is_null_before_a_full_window(make):
    report, clock, timer, _ = make()
    move_to(clock, timer, 100)
    body = report.report()
    assert all(c["psi"] is None for c in body["cities"])
    assert body["any_drift"] is False and body["reference_block"] == 0


def test_two_shifted_cities_trigger_drift(make):
    report, clock, timer, _ = make(min_cities=2)
    move_to(clock, timer, 200)
    body = report.report()
    assert body["sim_time"] == "2020-04-02T08:00:00"
    assert body["reference_block"] == 1 and body["cities_exceeding"] == 2
    assert [c["exceeds"] for c in body["cities"]] == [True, True, False]
    assert body["psi_condition"] is True and body["any_drift"] is True


def test_rule_needs_min_cities(make):
    report, clock, timer, _ = make(min_cities=3)
    move_to(clock, timer, 200)
    assert report.report()["any_drift"] is False


def test_mae_ratio_is_reported_but_not_part_of_the_rule(make):
    report, clock, timer, model = make(min_cities=3, model=Model(value=22.0))
    move_to(clock, timer, 200)
    body = report.report()
    # |22 - 10| / 4.0 = 3.0 for every city
    assert body["mae_ratio_pooled"] == 3.0 and body["mae_condition"] is True
    assert {c["mae_ratio_1h"] for c in body["cities"]} == {3.0}
    assert body["any_drift"] is False
    report.report()
    assert model.calls == 1  # cached for the same replay hour and version


def test_mae_ratio_waits_for_24_hours_and_survives_model_errors(make):
    model = Model()
    report, clock, timer, _ = make(model=model)
    move_to(clock, timer, 10)
    assert report.report()["mae_ratio_pooled"] is None and model.calls == 0
    model.up = False
    move_to(clock, timer, 200)
    body = report.report()
    assert body["mae_ratio_pooled"] is None and body["mae_condition"] is False
    assert body["cities_exceeding"] == 2  # PSI still works without the model


def test_mae_ratio_needs_the_champion_mae(make):
    report, clock, timer, model = make(registry=Registry(mae=None))
    move_to(clock, timer, 200)
    assert report.report()["mae_ratio_pooled"] is None and model.calls == 0


def test_summary_for_the_retrain_request(make):
    report, clock, timer, _ = make(model=Model(value=14.0))
    move_to(clock, timer, 200)
    summary = report.summary()
    assert summary["cities_exceeding"] == 2 and summary["mae_ratio_pooled"] == 1.0
    assert summary["psi_max"] > 0.5


def test_missing_reference_files_mean_no_votes(make, tmp_path):
    report, clock, timer, _ = make()
    (tmp_path / "reports" / "drift_thresholds.json").unlink()
    move_to(clock, timer, 200)
    body = report.report()
    assert body["cities_exceeding"] == 0 and not any(c["votes"] for c in body["cities"])


def test_store_window_has_full_length(make, tmp_path):
    store = ServingStore(tmp_path / "serving.parquet")
    rows = store.window(
        "A", pd.Timestamp("2020-03-17 22:00"), pd.Timestamp("2020-03-18 01:00")
    )
    assert len(rows) == 4 and rows["pm25_lag_1"].isna().sum() == 2
    assert store.window("Nowhere", rows.index[0], rows.index[-1]).shape[0] == 4
