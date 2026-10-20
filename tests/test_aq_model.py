import json

import joblib
import numpy as np
import pandas as pd
import pytest
from src.common.schema import FEATURE_COLUMNS, FEATURES
from src.pipeline import aq_model, modeling

from tests.test_modeling import make_frame


class FakeContext:
    def __init__(self, artifacts):
        self.artifacts = artifacts


def build_package(tmp_path, kinds):
    """Save one small model per horizon (kinds: horizon -> ridge/lightgbm).

    Returns (loaded AQForecaster, frame). ``kinds=None`` writes a meta.json
    without the ``kinds`` key, like a package from before Ridge was supported.
    """
    df = make_frame(800)
    artifacts = {}
    for horizon, target in [(1, "y_1h"), (24, "y_24h")]:
        train = df.dropna(subset=[target])
        if kinds and kinds[horizon] == "ridge":
            model = modeling.build_ridge(1.0)
            model.fit(train[FEATURE_COLUMNS], train[target])
            path = tmp_path / f"h{horizon}.joblib"
            joblib.dump(model, path)
        else:
            model = modeling.build_lightgbm({"n_estimators": 15, "n_jobs": 2}, seed=1)
            model.fit(modeling.lgbm_frame(train, 7), train[target])
            path = tmp_path / f"h{horizon}.txt"
            model.booster_.save_model(str(path))
        artifacts[f"h{horizon}"] = str(path)
    meta = {"feature_columns": FEATURE_COLUMNS, "n_cities": 7, "horizons": [1, 24]}
    if kinds:
        meta["kinds"] = {str(h): k for h, k in kinds.items()}
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(meta))
    artifacts["meta"] = str(meta_path)
    model = aq_model.AQForecaster()
    model.load_context(FakeContext(artifacts))
    return model, df


@pytest.fixture
def forecaster(tmp_path):
    """An AQForecaster with a LightGBM booster for each horizon."""
    return build_package(tmp_path, {1: "lightgbm", 24: "lightgbm"})


def request(df, horizons):
    rows = []
    for h in horizons:
        row = df[FEATURE_COLUMNS].iloc[[400]].copy()
        row.insert(0, "horizon_h", h)
        rows.append(row)
    return pd.concat(rows, ignore_index=True)[FEATURES]


def test_predicts_both_horizons_in_input_order(forecaster, monkeypatch):
    model, df = forecaster
    monkeypatch.setenv("AQ_MODEL_VERSION", "7")
    out = model.predict(None, request(df, [24, 1, 24]))
    assert list(out.columns) == ["pm25", "model_version"]
    assert len(out) == 3 and (out["model_version"] == "7").all()
    assert out.loc[0, "pm25"] == out.loc[2, "pm25"]  # same input, same model
    only_one = model.predict(None, request(df, [1]))
    only_day = model.predict(None, request(df, [24]))
    assert out.loc[1, "pm25"] == only_one.loc[0, "pm25"]
    assert out.loc[0, "pm25"] == only_day.loc[0, "pm25"]


def test_version_defaults_to_unversioned(forecaster, monkeypatch):
    model, df = forecaster
    monkeypatch.delenv("AQ_MODEL_VERSION", raising=False)
    assert model.predict(None, request(df, [1]))["model_version"][0] == "unversioned"


def test_accepts_missing_values(forecaster):
    model, df = forecaster
    req = request(df, [1, 24])
    req["pm25_lag_1"] = np.nan
    req["pm10_lag_1"] = np.nan
    out = model.predict(None, req)
    assert np.isfinite(out["pm25"]).all()


def test_never_returns_negative_values(forecaster):
    model, df = forecaster
    req = request(df, [1])
    req[["pm25_lag_1", "pm25_lag_2", "pm25_lag_3", "pm25_lag_24"]] = -500.0
    assert (model.predict(None, req)["pm25"] >= 0).all()


def test_rejects_missing_columns_and_unknown_horizon(forecaster):
    model, df = forecaster
    with pytest.raises(ValueError, match="Missing input columns"):
        model.predict(None, request(df, [1]).drop(columns=["hour"]))
    with pytest.raises(ValueError, match="Unsupported horizon_h"):
        model.predict(None, request(df, [6]))


def test_package_can_hold_ridge_for_one_horizon_and_lightgbm_for_the_other(tmp_path):
    model, df = build_package(tmp_path, {1: "ridge", 24: "lightgbm"})
    assert model.kinds == {1: "ridge", 24: "lightgbm"}
    out = model.predict(None, request(df, [24, 1]))
    assert np.isfinite(out["pm25"]).all() and (out["pm25"] >= 0).all()
    # the Ridge pipeline imputes gaps itself
    req = request(df, [1])
    req["pm25_lag_1"] = np.nan
    assert np.isfinite(model.predict(None, req)["pm25"]).all()


def test_meta_without_kinds_is_read_as_lightgbm(tmp_path):
    model, _ = build_package(tmp_path, None)
    assert model.kinds == {1: "lightgbm", 24: "lightgbm"}


def test_unknown_model_kind_is_refused(tmp_path):
    build_package(tmp_path, {1: "lightgbm", 24: "lightgbm"})
    meta = json.loads((tmp_path / "meta.json").read_text())
    meta["kinds"]["1"] = "forest"
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    artifacts = {
        "h1": str(tmp_path / "h1.txt"),
        "h24": str(tmp_path / "h24.txt"),
        "meta": str(tmp_path / "meta.json"),
    }
    with pytest.raises(ValueError, match="Unknown model kind"):
        aq_model.AQForecaster().load_context(FakeContext(artifacts))
