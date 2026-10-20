import numpy as np
import pandas as pd
import pytest
from src.common.schema import FEATURE_COLUMNS
from src.pipeline import modeling

CUTOFF = "2020-02-10 00:00:00"


def make_frame(n_hours=24 * 20, city="Delhi", seed=0):
    """Hourly rows ending at the cutoff, with targets, lags and all features."""
    rng = np.random.default_rng(seed)
    times = pd.date_range(end=CUTOFF, periods=n_hours, freq="h")
    base = 50 + 20 * np.sin(np.arange(n_hours) / 12) + rng.normal(0, 3, n_hours)
    df = pd.DataFrame({"City": city, "Datetime": times, "pm25": base})
    df["city_code"] = 0
    df["hour"] = times.hour
    df["dow"] = times.dayofweek
    df["month"] = times.month
    df["is_weekend"] = (times.dayofweek >= 5).astype(int)
    for k in (1, 2, 3, 24, 168):
        df[f"pm25_lag_{k}"] = df["pm25"].shift(k - 1)
    for n in (6, 24):
        df[f"pm25_roll_mean_{n}"] = df["pm25"].rolling(n, min_periods=1).mean()
    df["pm25_roll_std_24"] = df["pm25"].rolling(24, min_periods=2).std()
    for c in ("pm10", "no2", "co", "so2", "o3"):
        df[f"{c}_lag_1"] = rng.normal(30, 5, n_hours)
    df["y_1h"] = df["pm25"].shift(-1)
    df["y_24h"] = df["pm25"].shift(-24)
    return df


def test_split_purges_training_rows_and_limits_eval_rows():
    df = make_frame()
    train, ev = modeling.split_for_horizon(df, 24, CUTOFF, 3)
    eval_start = pd.Timestamp(CUTOFF) - pd.Timedelta(days=3)
    assert (train["Datetime"] + pd.Timedelta(hours=24) <= eval_start).all()
    assert (ev["Datetime"] > eval_start).all()
    # the 24 h targets of eval rows must exist, so origins stop 24 h before the end
    assert ev["Datetime"].max() == pd.Timestamp(CUTOFF) - pd.Timedelta(hours=24)
    assert set(train.index).isdisjoint(ev.index)


def test_split_drops_rows_without_target_or_baseline_lags():
    df = make_frame()
    df.loc[df.index[300], "y_1h"] = np.nan
    df.loc[df.index[330], "pm25_lag_24"] = np.nan
    train, ev = modeling.split_for_horizon(df, 1, CUTOFF, 3)
    assert df.index[300] not in train.index and df.index[300] not in ev.index
    assert df.index[330] not in ev.index


def test_recency_weights_halve_every_half_life():
    times = pd.Series(pd.to_datetime(["2020-02-10", "2020-01-11", "2019-12-12"]))
    w = modeling.recency_weights(times, CUTOFF, 30)
    assert w == pytest.approx([1.0, 0.5, 0.25])
    assert (
        modeling.recency_weights(times + pd.Timedelta(days=100), CUTOFF, 30) <= 1
    ).all()


def test_baseline_predictions_by_horizon():
    df = make_frame(300)
    one = modeling.baseline_predictions(df, 1)
    day = modeling.baseline_predictions(df, 24)
    assert np.array_equal(one["persistence"], df["pm25_lag_1"], equal_nan=True)
    assert np.array_equal(one["seasonal_naive"], df["pm25_lag_24"], equal_nan=True)
    # at 24 h the value one day before the target hour is the current hour
    assert np.array_equal(day["seasonal_naive"], day["persistence"], equal_nan=True)


def test_ridge_pipeline_imputes_with_indicator_and_predicts_with_gaps():
    df = make_frame(600)
    df.loc[df.index[::7], "pm10_lag_1"] = np.nan  # gaps only in this column
    train = df.dropna(subset=["y_1h"])
    model = modeling.build_ridge(1.0)
    model.fit(train[FEATURE_COLUMNS], train["y_1h"])
    imputer = model.named_steps["prep"].named_transformers_["num"].named_steps["impute"]
    # a flag column exists for pm10_lag_1, which had gaps in training
    assert modeling.NUMERIC.index("pm10_lag_1") in imputer.indicator_.features_
    row = train[FEATURE_COLUMNS].head(3).copy()
    row.loc[row.index[0], "pm25_lag_1"] = np.nan  # a gap never seen in training
    pred = model.predict(row)
    assert pred.shape == (3,) and np.isfinite(pred).all()


def test_ridge_indicator_flag_changes_the_prediction():
    df = make_frame(600)
    df.loc[df.index[::5], "pm10_lag_1"] = np.nan
    df["y_1h"] = df["y_1h"] + np.where(df["pm10_lag_1"].isna(), 25.0, 0.0)
    train = df.dropna(subset=["y_1h"])
    model = modeling.build_ridge(0.1)
    model.fit(train[FEATURE_COLUMNS], train["y_1h"])
    present = train[train["pm10_lag_1"].notna()][FEATURE_COLUMNS].head(1)
    missing = present.copy()
    missing["pm10_lag_1"] = np.nan
    assert model.predict(missing)[0] - model.predict(present)[0] > 10


def test_lgbm_frame_sets_fixed_city_categories():
    frame = modeling.lgbm_frame(make_frame(50), n_cities=7)
    assert frame["city_code"].dtype.categories.tolist() == list(range(7))
    assert list(frame.columns) == FEATURE_COLUMNS


def test_lightgbm_accepts_nulls_and_trains():
    df = make_frame(600)
    df.loc[df.index[::4], "pm25_lag_24"] = np.nan
    train = df.dropna(subset=["y_1h"])
    model = modeling.build_lightgbm({"n_estimators": 20, "n_jobs": 2}, seed=1)
    model.fit(modeling.lgbm_frame(train, 7), train["y_1h"])
    assert np.isfinite(model.predict(modeling.lgbm_frame(train, 7))).all()


def test_error_metrics_and_high_values():
    m = modeling.error_metrics([10, 20, 30], [12, 18, 36])
    assert m["mae"] == pytest.approx(10 / 3) and m["n"] == 3
    assert m["rmse"] == pytest.approx(np.sqrt((4 + 4 + 36) / 3))
    high = modeling.high_value_metrics([10, 130, 200], [12, 100, 210], 121)
    assert high["n"] == 2 and high["mae"] == pytest.approx(20.0)
    assert modeling.high_value_metrics([10, 20], [1, 2], 121) is None


def test_per_city_table_and_best_baseline():
    ev = pd.DataFrame({"City": ["A", "A", "B"], "y_1h": [10.0, 20.0, 30.0]})
    table = modeling.per_city_table(
        ev, 1, {"persistence": np.array([11.0, 19.0, 35.0])}
    )
    rows = table.set_index("city")
    assert rows.loc["A", "mae"] == 1.0 and rows.loc["B", "mae"] == 5.0
    assert set(table["horizon_h"]) == {1} and set(table["model"]) == {"persistence"}
    metrics = {
        "persistence": {"mae": 5.0},
        "seasonal_naive": {"mae": 4.0},
        "ridge": {"mae": 6.0},
    }
    assert modeling.best_baseline(metrics) == ("seasonal_naive", 4.0)


def test_lightgbm_training_is_repeatable():
    df = make_frame(1500)
    train = df.dropna(subset=["y_24h"])
    weights = modeling.recency_weights(train["Datetime"], CUTOFF, 30)
    preds = []
    for _ in range(3):
        model = modeling.build_lightgbm(
            {"objective": "regression_l1", "n_estimators": 30, "n_jobs": 4}, seed=3
        )
        model.fit(modeling.lgbm_frame(train, 7), train["y_24h"], sample_weight=weights)
        preds.append(model.predict(modeling.lgbm_frame(train, 7)))
    assert np.array_equal(preds[0], preds[1]) and np.array_equal(preds[1], preds[2])


def test_choose_model_picks_lower_mae_and_ties_go_to_lightgbm():
    def metrics(ridge, lgbm):
        return {"ridge": {"mae": ridge}, "lightgbm": {"mae": lgbm}}

    assert modeling.choose_model(metrics(4.0, 5.0)) == "ridge"
    assert modeling.choose_model(metrics(5.0, 4.0)) == "lightgbm"
    assert modeling.choose_model(metrics(4.0, 4.0)) == "lightgbm"
