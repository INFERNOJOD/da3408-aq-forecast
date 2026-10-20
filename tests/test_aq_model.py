import json

import numpy as np
import pandas as pd
import pytest
from src.common.schema import FEATURE_COLUMNS, FEATURES
from src.pipeline import aq_model, modeling

from tests.test_modeling import make_frame


class FakeContext:
    def __init__(self, artifacts):
        self.artifacts = artifacts


@pytest.fixture
def forecaster(tmp_path):
    """An AQForecaster loaded from two small boosters saved in a temp folder."""
    df = make_frame(800)
    artifacts = {}
    for horizon, target in [(1, "y_1h"), (24, "y_24h")]:
        train = df.dropna(subset=[target])
        model = modeling.build_lightgbm({"n_estimators": 15, "n_jobs": 2}, seed=1)
        model.fit(modeling.lgbm_frame(train, 7), train[target])
        path = tmp_path / f"h{horizon}.txt"
        model.booster_.save_model(str(path))
        artifacts[f"h{horizon}"] = str(path)
    meta = tmp_path / "meta.json"
    meta.write_text(
        json.dumps(
            {"feature_columns": FEATURE_COLUMNS, "n_cities": 7, "horizons": [1, 24]}
        )
    )
    artifacts["meta"] = str(meta)
    model = aq_model.AQForecaster()
    model.load_context(FakeContext(artifacts))
    return model, df


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
