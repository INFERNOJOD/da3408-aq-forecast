"""Tests for scripts/replay.py (the offline drift acceptance replay)."""

from datetime import datetime

import numpy as np
import pandas as pd
from scripts import replay
from src.monitoring.drift import DriftDetector

START = datetime(2020, 3, 25)


def frame(years, cities=("A", "B"), hours=48, low=()):
    """pm25_lag_1 for the first ``hours`` of each year's window; ``low`` = shifted."""
    rows = []
    for year in years:
        for city in cities:
            t = pd.date_range(f"{year}-03-25", periods=hours, freq="h")
            values = np.tile([5.0, 15.0, 25.0, 35.0], hours // 4)
            if (city, year) in low:
                values = np.full(hours, 1.0)
            rows.append(
                pd.DataFrame({"City": city, "Datetime": t, "pm25_lag_1": values})
            )
    return pd.concat(rows, ignore_index=True)


def test_add_replay_hour_aligns_on_the_start_date():
    df = frame([2016, 2019], hours=4)
    extra = pd.DataFrame({"City": ["A"], "Datetime": [pd.Timestamp("2019-03-24 23:00")],
                          "pm25_lag_1": [1.0]})  # fmt: skip
    out = replay.add_replay_hour(pd.concat([df, extra]), START, 3)
    assert sorted(out["rh"].unique()) == [0, 1, 2]
    assert set(out["year"]) == {2016, 2019}  # leap year 2016 still starts at 0


def test_episodes_group_consecutive_hours():
    flags = pd.Series([False, True, True, False, True], index=[10, 11, 12, 13, 14])
    out = replay.episodes(flags, START)
    assert [e["hours"] for e in out] == [2, 1]
    assert out[0]["first"] == "2020-03-25 11:00:00"


def test_loyo_reference_leaves_the_year_out():
    df = replay.add_replay_hour(frame([2017, 2018, 2019], low={("A", 2019)}), START, 48)
    ref = replay.loyo_reference(df, "A", 2019, [2017, 2018, 2019], 4, 24)
    assert len(ref) == 2 and ref[0]["edges"] == [5.0, 15.0, 25.0]


def run_years(low=()):
    years = [2017, 2018, 2019]
    df = replay.add_replay_hour(frame(years, low=low), START, 48)
    out = {}
    for year in years:
        ref = {c: replay.loyo_reference(df, c, year, years, 4, 24) for c in ("A", "B")}
        det = DriftDetector(ref, {"A": 0.5, "B": 0.5}, 2, 24)
        out[year] = replay.replay_year(df, year, det, START, 48)
    return out


def test_replay_year_is_quiet_when_years_agree():
    assert all(r["drift_hours"] == 0 for r in run_years().values())


def test_replay_year_counts_drift_hours():
    shifted = run_years(low={("A", 2019), ("B", 2019)})[2019]
    assert shifted["drift_hours"] == shifted["hours_scored"] == 25
    assert shifted["first_drift"] == "2019-03-25 23:00:00"
    assert shifted["exceed_hours_per_city"] == {"A": 25, "B": 25}
    assert shifted["hours_with_at_least_k_cities"]["2"] == 25
    assert len(shifted["episodes"]) == 1
