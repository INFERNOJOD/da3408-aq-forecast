"""Pure functions for the training stage: splits, weights, models and scores.

Nothing here touches the disk or MLflow, so it is easy to test. The training
stage (train.py) calls these functions and does the logging.

Time rules (see docs/HLD.md, "Time split"):
  * The evaluation window is the last ``eval_window_days`` before the cutoff.
  * Training rows are purged: a row only trains if its target hour is at or
    before the start of the evaluation window. Otherwise the 24 h target of a
    training row would overlap the window we score on.
  * Training rows are weighted by recency with a half-life, so the model follows
    the most recent regime.
"""

from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.common.schema import FEATURE_COLUMNS, HORIZONS

BASELINES = ("persistence", "seasonal_naive", "ridge")
CATEGORICAL = ["city_code", "hour", "dow", "month"]  # one-hot for Ridge
NUMERIC = [c for c in FEATURE_COLUMNS if c not in CATEGORICAL]


def split_for_horizon(
    df: pd.DataFrame, horizon: int, cutoff: str, eval_window_days: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split feature rows into (train, eval) for one horizon.

    Rows without a target are dropped. Eval rows also need the two lags that the
    naive baselines use, so every model is scored on exactly the same rows.
    """
    target = HORIZONS[horizon]
    eval_start = pd.Timestamp(cutoff) - pd.Timedelta(days=eval_window_days)
    has_target = df[target].notna()
    train = df[
        has_target & (df["Datetime"] + pd.Timedelta(hours=horizon) <= eval_start)
    ]
    scorable = df["pm25_lag_1"].notna() & df["pm25_lag_24"].notna()
    evaluation = df[has_target & (df["Datetime"] > eval_start) & scorable]
    return train, evaluation


def recency_weights(times: pd.Series, cutoff: str, half_life_days: float) -> np.ndarray:
    """Weight 1 at the cutoff, 0.5 one half-life earlier, 0.25 two earlier, ..."""
    age_days = (pd.Timestamp(cutoff) - times).dt.total_seconds() / 86400.0
    return np.power(0.5, age_days.clip(lower=0) / half_life_days).to_numpy()


def baseline_predictions(df: pd.DataFrame, horizon: int) -> dict[str, np.ndarray]:
    """Predictions of the two rule-based baselines.

    persistence: the latest value stays. seasonal_naive: the value one day before
    the target hour. For horizon 1 that is lag 24. For horizon 24 it is the
    current hour, so there the two baselines are identical.
    """
    seasonal = "pm25_lag_24" if horizon == 1 else "pm25_lag_1"
    return {
        "persistence": df["pm25_lag_1"].to_numpy(),
        "seasonal_naive": df[seasonal].to_numpy(),
    }


def build_ridge(alpha: float) -> Pipeline:
    """Ridge inside an sklearn pipeline that handles missing values itself.

    Numeric columns: median imputer that also adds a missing-indicator flag for
    every column that had gaps in training, then scaling. Calendar and city
    columns: one-hot. The imputer is fitted on training rows only and is part of
    the pipeline, so training and prediction treat gaps the same way.
    """
    numeric = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
        ]
    )
    prep = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
            ("num", numeric, NUMERIC),
        ]
    )
    return Pipeline([("prep", prep), ("ridge", Ridge(alpha=alpha))])


def lgbm_frame(df: pd.DataFrame, n_cities: int) -> pd.DataFrame:
    """Model input for LightGBM: feature columns, city_code as a category."""
    frame = df[FEATURE_COLUMNS].copy()
    frame["city_code"] = (
        frame["city_code"]
        .astype(int)
        .astype(pd.CategoricalDtype(list(range(n_cities))))
    )
    return frame


def build_lightgbm(params: dict[str, Any], seed: int) -> LGBMRegressor:
    """LightGBM regressor from the params.yaml settings. Gain-based importances.

    Training is deterministic by default. Without ``deterministic`` and
    ``force_row_wise``, two runs with the same seed and data differ (predictions
    moved by up to about 5 µg/m³ in my test), and a run could not be reproduced
    from its git commit and data version.
    """
    settings = {"deterministic": True, "force_row_wise": True, **params}
    return LGBMRegressor(
        **settings, random_state=seed, importance_type="gain", verbose=-1
    )


def error_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Mean absolute error, root mean squared error and the row count."""
    err = np.asarray(y_pred, dtype=float) - np.asarray(y_true, dtype=float)
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "n": int(len(err)),
    }


def high_value_metrics(
    y_true: np.ndarray, y_pred: np.ndarray, threshold: float
) -> dict[str, float] | None:
    """Error on hours where the actual PM2.5 is at or above ``threshold``.

    Returns None when there are no such hours. Extreme hours are rare, so they
    are reported on their own (see docs/eda.md, bias 5).
    """
    y_true = np.asarray(y_true, dtype=float)
    mask = y_true >= threshold
    if not mask.any():
        return None
    return error_metrics(y_true[mask], np.asarray(y_pred, dtype=float)[mask])


def per_city_table(
    evaluation: pd.DataFrame, horizon: int, predictions: dict[str, np.ndarray]
) -> pd.DataFrame:
    """MAE, RMSE and row count per model and city for one horizon."""
    target = HORIZONS[horizon]
    rows = []
    for model, pred in predictions.items():
        frame = evaluation.assign(_pred=np.asarray(pred, dtype=float))
        for city, part in frame.groupby("City"):
            m = error_metrics(part[target], part["_pred"])
            rows.append({"model": model, "horizon_h": horizon, "city": city, **m})
    return pd.DataFrame(rows)


def best_baseline(metrics: dict[str, dict[str, float]]) -> tuple[str, float]:
    """Name and MAE of the best of persistence, seasonal_naive and ridge."""
    name = min(BASELINES, key=lambda m: metrics[m]["mae"])
    return name, metrics[name]["mae"]
