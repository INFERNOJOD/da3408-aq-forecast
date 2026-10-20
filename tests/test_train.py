import json

import mlflow
import numpy as np
import pandas as pd
import pytest
from src.common.errors import DataValidationError
from src.common.schema import FEATURE_COLUMNS, FEATURES, HORIZONS
from src.pipeline import train

from tests.test_modeling import CUTOFF, make_frame

CITIES = ["Delhi", "Chennai"]


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


def test_model_signature_matches_the_lld_columns():
    names = [c.name for c in train.model_signature().inputs.inputs]
    assert names == FEATURES


def test_flatten_nested_settings():
    out = train.flatten("train", {"a": 1, "b": {"c": 2, "d": {"e": 3}}}, {})
    assert out == {"train.a": 1, "train.b.c": 2, "train.b.d.e": 3}


def test_drift_scores_only_numbers(tmp_path):
    assert train.drift_scores(tmp_path) == {}
    (tmp_path / "drift_trigger.json").write_text(
        json.dumps({"psi_max": 0.41, "mae_ratio": 1.8, "city": "Delhi", "flag": True})
    )
    assert train.drift_scores(tmp_path) == {
        "drift_psi_max": 0.41,
        "drift_mae_ratio": 1.8,
    }
    (tmp_path / "drift_trigger.json").write_text("not json")
    assert train.drift_scores(tmp_path) == {}


def test_load_features_missing_file(tmp_path):
    with pytest.raises(DataValidationError, match="Run features first"):
        train.load_features(tmp_path / "nope.parquet")


def test_fit_horizon_scores_all_four_models(params, tmp_path):
    df = train.load_features(tmp_path / "features" / "train.parquet")
    res = train.fit_horizon(df, 1, params)
    assert set(res["metrics"]) == {"persistence", "seasonal_naive", "ridge", "lightgbm"}
    assert {m["n"] for m in res["metrics"].values()} == {res["n_eval"]}  # same rows
    assert res["ratio_to_best_baseline"] == pytest.approx(
        res["metrics"]["lightgbm"]["mae"] / res["best_baseline"]["mae"]
    )
    assert set(res["per_city"]["city"]) == set(CITIES)
    assert res["n_train"] > 0 and res["effective_n"] <= res["n_train"]


def test_fit_horizon_fails_clearly_without_enough_rows(params, tmp_path):
    df = train.load_features(tmp_path / "features" / "train.parquet")
    params["cutoff"] = "2019-01-01 00:00:00"
    with pytest.raises(DataValidationError, match="evaluation rows"):
        train.fit_horizon(df, 24, params)


def test_run_train_logs_beyond_autolog_and_saves_a_servable_model(
    params, tracking, tmp_path, monkeypatch
):
    monkeypatch.setenv("PIPELINE_TRIGGER", "initial")
    (tmp_path / "reports" / "drift_trigger.json").write_text('{"psi_max": 0.5}')
    result = train.run_train(params)
    assert result["rows_in"] == 2 * 24 * 40 and result["rows_out"] > 0

    doc = json.loads((tmp_path / "reports" / "train_metrics.json").read_text())
    run = mlflow.get_run(doc["run_id"])
    tags, metrics = run.data.tags, run.data.metrics
    assert tags["git_commit"] == doc["git_commit"]  # "unknown" outside a git repo
    assert tags["dvc_data_md5"] == "deadbeef.dir" and tags["features_md5"]
    assert tags["trigger"] == "initial"
    assert tags["git_dirty"] in ("true", "false") and tags["cutoff"] == CUTOFF
    for model in ("persistence", "seasonal_naive", "ridge", "lightgbm"):
        for h in (1, 24):
            assert f"{model}_mae_{h}h" in metrics and f"{model}_rmse_{h}h" in metrics
            for city in CITIES:
                assert f"{model}_mae_{h}h_{city}" in metrics  # per city and horizon
    for h in (1, 24):
        assert f"ratio_lightgbm_to_best_baseline_{h}h" in metrics
    assert "lightgbm_mean_mae" in metrics and metrics["drift_psi_max"] == 0.5
    assert run.data.params["train.lightgbm.n_estimators"] == "25"
    assert run.data.params["cutoff"] == CUTOFF

    client = mlflow.MlflowClient()
    files = {a.path for a in client.list_artifacts(doc["run_id"])}
    assert {
        "per_city_mae.csv",
        "feature_importance.png",
        "residuals.png",
        "drift_baseline.json",
        "params_resolved.json",
        "environment_pins.txt",
    } <= files

    # The saved candidate answers requests that follow the LLD input columns.
    model = mlflow.pyfunc.load_model(str(tmp_path / "models" / "candidate"))
    df = train.load_features(tmp_path / "features" / "train.parquet")
    rows = df[FEATURE_COLUMNS].dropna().head(2).copy()
    rows.insert(0, "horizon_h", [1, 24])
    rows = rows.astype({c: "int64" for c in train.INT_COLUMNS})
    out = model.predict(rows[FEATURES])
    assert list(out.columns) == ["pm25", "model_version"] and (out["pm25"] >= 0).all()


def test_run_train_is_repeatable_for_a_new_cutoff(params, tracking, tmp_path):
    train.run_train(params)
    params["cutoff"] = "2020-02-09 00:00:00"  # a retrain at an earlier cutoff
    train.run_train(params)
    runs = mlflow.search_runs(experiment_names=["aq-test"])
    assert len(runs) == 2
    assert (
        tmp_path / "models" / "candidate" / "MLmodel"
    ).exists()  # replaced, not stacked
