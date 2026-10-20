"""The packaged model: one MLflow pyfunc that answers both forecast horizons.

MLflow loads this file by itself inside the model server (the "models from code"
way), so it imports nothing from the rest of ``src``. The feature names and the
number of cities come from ``meta.json``, which the training stage saves next to
the per-horizon model files. For each horizon the training stage keeps the
better of Ridge and LightGBM, so ``meta.json`` also says which kind each horizon
holds (``kinds``): a LightGBM booster is a ``.txt`` file, a Ridge pipeline is a
``.joblib`` file. A package without ``kinds`` is read as all LightGBM.

Input: a DataFrame with the columns listed in docs/LLD.md section 4, one row per
(city, horizon). The column ``horizon_h`` (1 or 24) picks the model.
Output: a DataFrame with ``pm25`` (µg/m³, never below 0) and ``model_version``.
"""

import json
import logging
import os

import joblib
import lightgbm as lgb
import mlflow
import mlflow.pyfunc
import pandas as pd

log = logging.getLogger(__name__)

VERSION_ENV = "AQ_MODEL_VERSION"  # set by the model server wrapper (see LLD)


def lgbm_frame(
    df: pd.DataFrame, feature_columns: list[str], n_cities: int
) -> pd.DataFrame:
    """Return the model input: columns in training order, city_code as category.

    LightGBM was trained with ``city_code`` as a categorical column with the
    fixed categories 0..n_cities-1. The same cast is needed at prediction time.
    """
    frame = df[feature_columns].copy()
    frame["city_code"] = (
        frame["city_code"]
        .astype(int)
        .astype(pd.CategoricalDtype(list(range(n_cities))))
    )
    return frame


class AQForecaster(mlflow.pyfunc.PythonModel):
    """Forecast PM2.5 for 1 h and 24 h ahead, Ridge or LightGBM per horizon."""

    def load_context(self, context) -> None:
        """Load the per-horizon models and the metadata from the artifacts."""
        with open(context.artifacts["meta"], encoding="utf-8") as fh:
            self.meta = json.load(fh)
        kinds = self.meta.get("kinds", {})
        self.kinds = {}
        self.models = {}
        for h in self.meta["horizons"]:
            kind = kinds.get(str(h), "lightgbm")
            path = context.artifacts[f"h{h}"]
            if kind == "ridge":
                self.models[int(h)] = joblib.load(path)
            elif kind == "lightgbm":
                self.models[int(h)] = lgb.Booster(model_file=path)
            else:
                raise ValueError(f"Unknown model kind {kind!r} for horizon {h}")
            self.kinds[int(h)] = kind
        log.info("Loaded AQ model: %s", self.kinds)

    def predict(self, context, model_input, params=None) -> pd.DataFrame:
        """Predict PM2.5 for every input row, keeping the row order."""
        df = pd.DataFrame(model_input)
        wanted = ["horizon_h", *self.meta["feature_columns"]]
        missing = [c for c in wanted if c not in df.columns]
        if missing:
            raise ValueError(f"Missing input columns: {missing}")
        horizons = df["horizon_h"].astype(int)
        unknown = sorted(set(horizons) - set(self.models))
        if unknown:
            raise ValueError(
                f"Unsupported horizon_h {unknown}; use one of {sorted(self.models)}"
            )
        out = pd.Series(0.0, index=df.index)
        for horizon, model in self.models.items():
            rows = df[horizons == horizon]
            if rows.empty:
                continue
            if self.kinds[horizon] == "ridge":
                frame = rows[self.meta["feature_columns"]]  # imputer is in the pipeline
            else:
                frame = lgbm_frame(
                    rows, self.meta["feature_columns"], self.meta["n_cities"]
                )
            out.loc[rows.index] = model.predict(frame)
        version = os.environ.get(VERSION_ENV, "unversioned")
        return pd.DataFrame(
            {"pm25": out.clip(lower=0.0).round(2).to_numpy(), "model_version": version}
        )


mlflow.models.set_model(AQForecaster())
