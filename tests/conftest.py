"""Shared test fixtures."""

import logging

import numpy as np
import pandas as pd
import pytest
from src.common.schema import HORIZONS
from src.common.spark import build_spark

from tests.test_modeling import CUTOFF, make_frame

CITIES = ["Delhi", "Chennai"]


@pytest.fixture(scope="session")
def spark():
    """One small local Spark session shared by all tests (startup is slow)."""
    session = build_spark(
        "aq-tests", {"driver_memory": "512m", "shuffle_partitions": 2, "cores": 2}
    )
    yield session
    session.stop()
    # py4j logs "Closing down clientserver connection" at INFO from __del__
    # when Python exits. If that runs after pytest has closed the stderr the
    # root handler writes to, logging prints "--- Logging error ---
    # ValueError: I/O operation on closed file" (it depends on when the
    # garbage collector runs, so only some runs show it, e.g.
    # docs/evidence/07_source_control_ci/03_ci_run.txt of 2026-11-10).
    # Nothing is lost by dropping py4j's INFO messages once Spark is stopped.
    logging.getLogger("py4j").setLevel(logging.WARNING)


def synthetic_features(tmp_path):
    """Write a train.parquet like the features stage (targets cut at the cutoff)."""
    frames = []
    for code, city in enumerate(CITIES):
        df = make_frame(24 * 40, city=city, seed=code)
        df["city_code"] = code
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    cutoff = pd.Timestamp(CUTOFF)
    for horizon, name in HORIZONS.items():
        late = df["Datetime"] + pd.Timedelta(hours=horizon) > cutoff
        df.loc[late, name] = np.nan
    path = tmp_path / "features" / "train.parquet"
    path.parent.mkdir()
    df.to_parquet(path, index=False)
    return path


@pytest.fixture
def params(tmp_path):
    synthetic_features(tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir()
    (tmp_path / "raw.dvc").write_text("outs:\n- md5: deadbeef.dir\n  path: raw\n")
    (reports / "baseline_stats.json").write_text('{"feature": "pm25_lag_1"}')
    return {
        "paths": {
            "features_dir": str(tmp_path / "features"),
            "reports_dir": str(reports),
            "models_dir": str(tmp_path / "models"),
            "raw_dvc": str(tmp_path / "raw.dvc"),
        },
        "cities": CITIES,
        "cutoff": CUTOFF,
        "eval_window_days": 3,
        "train": {
            "experiment": "aq-test",
            "half_life_days": 30,
            "seed": 1,
            "high_pm25_threshold": 60,
            "ridge": {"alpha": 1.0},
            "lightgbm": {"n_estimators": 25, "learning_rate": 0.1, "n_jobs": 2},
        },
    }


@pytest.fixture
def tracking(tmp_path, monkeypatch):
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.delenv("PIPELINE_TRIGGER", raising=False)
    monkeypatch.chdir(tmp_path)  # MLflow writes artifacts under ./mlruns
    return uri
