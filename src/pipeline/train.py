"""Stage 4 of the DVC pipeline: train and score the models, log everything.

For each horizon (1 h and 24 h) this fits Ridge and LightGBM and scores them
together with two rule-based baselines (persistence, seasonal naive) on the same
evaluation window. Then it logs one MLflow run and saves the candidate model.

Beyond what MLflow autolog would record, the run holds: the git commit and
whether the working tree was clean, the DVC data version, per-city and
per-horizon errors for every model, the comparison with the best baseline, the
drift baseline used for monitoring, feature importance and residual plots, and
the drift scores that triggered a retrain (when there are any).

Run: ``python -m src.pipeline.train``
"""

import json
import os
import shutil
import tempfile
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import mlflow
import mlflow.pyfunc
import numpy as np
import pandas as pd
from mlflow.models.signature import ModelSignature
from mlflow.types import ColSpec, Schema

from src.common.config import load_env, load_params
from src.common.errors import DataValidationError
from src.common.logging_setup import configure_logging, get_logger
from src.common.schema import FEATURE_COLUMNS, FEATURES, HORIZONS
from src.common.stage_runner import run_stage
from src.common.versioning import (
    dvc_raw_md5,
    git_commit,
    git_dirty,
    parquet_data_md5,
)
from src.pipeline import modeling
from src.pipeline.train_plots import plot_feature_importance, plot_residuals

log = get_logger(__name__)

MODEL_FILE = Path(__file__).with_name("aq_model.py")
DEFAULT_TRACKING_URI = "sqlite:///mlflow.db"
INT_COLUMNS = {"horizon_h", "city_code", "hour", "dow", "month", "is_weekend"}


def load_features(path: str | Path) -> pd.DataFrame:
    """Read the training features written by the features stage."""
    path = Path(path)
    if not path.exists():
        raise DataValidationError(
            f"Feature file not found: {path}. Run features first."
        )
    df = pd.read_parquet(path)
    if df["Datetime"].dt.tz is not None:  # keep wall-clock labels, as in the CSV
        df["Datetime"] = df["Datetime"].dt.tz_localize(None)
    return df


def fit_horizon(
    df: pd.DataFrame, horizon: int, params: dict[str, Any]
) -> dict[str, Any]:
    """Fit Ridge and LightGBM for one horizon and score all four models.

    Returns the fitted LightGBM, all metrics, per-city errors and the data
    needed for the plots.
    """
    tp = params["train"]
    target = HORIZONS[horizon]
    train, evaluation = modeling.split_for_horizon(
        df, horizon, params["cutoff"], params["eval_window_days"]
    )
    if train.empty or evaluation.empty:
        raise DataValidationError(
            f"Horizon {horizon} h: {len(train)} training and {len(evaluation)} "
            "evaluation rows. Check the cutoff and eval_window_days."
        )
    weights = modeling.recency_weights(
        train["Datetime"], params["cutoff"], tp["half_life_days"]
    )
    n_cities = len(params["cities"])
    y = train[target]

    preds = modeling.baseline_predictions(evaluation, horizon)
    started = time.perf_counter()
    ridge = modeling.build_ridge(tp["ridge"]["alpha"])
    ridge.fit(train[FEATURE_COLUMNS], y, ridge__sample_weight=weights)
    preds["ridge"] = ridge.predict(evaluation[FEATURE_COLUMNS])
    ridge_seconds = time.perf_counter() - started

    started = time.perf_counter()
    lgbm = modeling.build_lightgbm(tp["lightgbm"], tp["seed"])
    lgbm.fit(modeling.lgbm_frame(train, n_cities), y, sample_weight=weights)
    preds["lightgbm"] = lgbm.predict(modeling.lgbm_frame(evaluation, n_cities))
    lgbm_seconds = time.perf_counter() - started
    # PM2.5 cannot be negative; the served model clips the same way.
    for name in ("ridge", "lightgbm"):
        preds[name] = np.clip(preds[name], 0.0, None)

    actual = evaluation[target].to_numpy()
    metrics = {name: modeling.error_metrics(actual, p) for name, p in preds.items()}
    high = modeling.high_value_metrics(
        actual, preds["lightgbm"], tp["high_pm25_threshold"]
    )
    best_name, best_mae = modeling.best_baseline(metrics)
    effective_n = float(weights.sum() ** 2 / np.sum(weights**2))
    log.info(
        "Horizon %d h: train %d rows (effective %.0f), eval %d rows, MAE %s",
        horizon,
        len(train),
        effective_n,
        len(evaluation),
        {k: round(v["mae"], 2) for k, v in metrics.items()},
    )
    return {
        "horizon": horizon,
        "lgbm": lgbm,
        "n_train": len(train),
        "n_eval": len(evaluation),
        "effective_n": effective_n,
        "metrics": metrics,
        "high_value": high,
        "best_baseline": {"name": best_name, "mae": best_mae},
        "ratio_to_best_baseline": metrics["lightgbm"]["mae"] / best_mae,
        "per_city": modeling.per_city_table(evaluation, horizon, preds),
        "importance": pd.Series(
            lgbm.feature_importances_, index=FEATURE_COLUMNS, dtype=float
        ),
        "residuals": preds["lightgbm"] - actual,
        "fit_seconds": {"ridge": ridge_seconds, "lightgbm": lgbm_seconds},
        "eval_example": evaluation.dropna(subset=FEATURE_COLUMNS).head(1),
    }


def summarize(results: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Collect the numbers that the promotion rule and the report use."""
    models = modeling.BASELINES + ("lightgbm",)
    mean_mae = {
        m: float(np.mean([results[h]["metrics"][m]["mae"] for h in results]))
        for m in models
    }
    return {
        "mean_mae": mean_mae,
        "ratio_to_best_baseline": {
            h: results[h]["ratio_to_best_baseline"] for h in results
        },
    }


def drift_scores(reports_dir: Path) -> dict[str, float]:
    """Read the drift scores that triggered this retrain, if there are any.

    The ops runner writes reports/drift_trigger.json before it starts a retrain
    caused by a drift alert. Only numbers are kept.
    """
    path = reports_dir / "drift_trigger.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("%s is not valid JSON; drift scores not logged", path)
        return {}
    return {
        f"drift_{k}": float(v)
        for k, v in raw.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def flatten(prefix: str, value: Any, out: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested settings into 'a.b.c' keys for MLflow params."""
    if isinstance(value, dict):
        for key, inner in value.items():
            flatten(f"{prefix}.{key}" if prefix else str(key), inner, out)
    else:
        out[prefix] = value
    return out


def model_signature() -> ModelSignature:
    """Input and output columns of the served model (docs/LLD.md, section 4)."""
    inputs = Schema(
        [ColSpec("long" if c in INT_COLUMNS else "double", c) for c in FEATURES]
    )
    outputs = Schema([ColSpec("double", "pm25"), ColSpec("string", "model_version")])
    return ModelSignature(inputs=inputs, outputs=outputs)


def write_model_files(
    results: dict[int, dict[str, Any]], n_cities: int, folder: Path
) -> dict[str, str]:
    """Save both boosters and meta.json into ``folder``; return the artifact map."""
    artifacts = {}
    for horizon, res in results.items():
        path = folder / f"h{horizon}.txt"
        res["lgbm"].booster_.save_model(str(path))
        artifacts[f"h{horizon}"] = str(path)
    meta = {
        "feature_columns": FEATURE_COLUMNS,
        "n_cities": n_cities,
        "horizons": sorted(results),
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    artifacts["meta"] = str(folder / "meta.json")
    return artifacts


def pip_requirements() -> list[str]:
    """Exact package versions the served model needs (same as this environment)."""
    return [
        f"{name}=={version(name)}" for name in ("mlflow", "lightgbm", "pandas", "numpy")
    ]


def log_run(
    params: dict[str, Any],
    results: dict[int, dict[str, Any]],
    summary: dict[str, Any],
    versions: dict[str, Any],
    reports_dir: Path,
    candidate_dir: Path,
) -> tuple[str, str]:
    """Create the MLflow run, log everything, and save the candidate model.

    Returns (run_id, model_uri).
    """
    tp = params["train"]
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
    mlflow.set_experiment(tp["experiment"])
    city_table = pd.concat([r["per_city"] for r in results.values()], ignore_index=True)

    with (
        mlflow.start_run(run_name=f"train-{params['cutoff']}") as run,
        tempfile.TemporaryDirectory() as tmp,
    ):
        tmp_dir = Path(tmp)
        trigger = os.environ.get("PIPELINE_TRIGGER", "manual")
        mlflow.set_tags(
            {
                "git_commit": versions["git_commit"],
                "git_dirty": str(versions["git_dirty"]).lower(),
                "dvc_data_md5": versions["dvc_data_md5"],
                "features_md5": versions["features_md5"],
                "cutoff": params["cutoff"],
                "trigger": trigger,
                "pipeline_run_id": os.environ.get("PIPELINE_RUN_ID", ""),
                "stage": "train",
            }
        )
        mlflow.log_params(flatten("train", tp, {}))
        mlflow.log_params(
            {
                "cutoff": params["cutoff"],
                "eval_window_days": params["eval_window_days"],
                "cities": ",".join(params["cities"]),
                "features": ",".join(FEATURES),
                **{f"n_train_{h}h": r["n_train"] for h, r in results.items()},
                **{f"n_eval_{h}h": r["n_eval"] for h, r in results.items()},
                **{
                    f"effective_n_{h}h": round(r["effective_n"])
                    for h, r in results.items()
                },
            }
        )

        metrics: dict[str, float] = {}
        for h, res in results.items():
            for model, m in res["metrics"].items():
                metrics[f"{model}_mae_{h}h"] = m["mae"]
                metrics[f"{model}_rmse_{h}h"] = m["rmse"]
            metrics[f"ratio_lightgbm_to_best_baseline_{h}h"] = res[
                "ratio_to_best_baseline"
            ]
            metrics[f"best_baseline_mae_{h}h"] = res["best_baseline"]["mae"]
            if res["high_value"]:
                metrics[f"lightgbm_mae_{h}h_high_pm25"] = res["high_value"]["mae"]
                metrics[f"n_high_pm25_{h}h"] = res["high_value"]["n"]
            for key, secs in res["fit_seconds"].items():
                metrics[f"fit_seconds_{key}_{h}h"] = secs
        for model, mae in summary["mean_mae"].items():
            metrics[f"{model}_mean_mae"] = mae
        for row in city_table.itertuples():
            metrics[f"{row.model}_mae_{row.horizon_h}h_{row.city}"] = row.mae
        metrics.update(drift_scores(reports_dir))
        mlflow.log_metrics(metrics)

        # Artifacts: tables, plots, the drift baseline, and the resolved settings.
        city_table.round(4).to_csv(tmp_dir / "per_city_mae.csv", index=False)
        mlflow.log_artifact(str(tmp_dir / "per_city_mae.csv"))
        mlflow.log_artifact(
            str(
                plot_feature_importance(
                    {h: r["importance"] for h, r in results.items()},
                    tmp_dir / "feature_importance.png",
                )
            )
        )
        mlflow.log_artifact(
            str(
                plot_residuals(
                    {h: r["residuals"] for h, r in results.items()},
                    tmp_dir / "residuals.png",
                )
            )
        )
        baseline = reports_dir / "baseline_stats.json"
        if baseline.is_file():
            shutil.copy(baseline, tmp_dir / "drift_baseline.json")
            mlflow.log_artifact(str(tmp_dir / "drift_baseline.json"))
        mlflow.log_dict(params, "params_resolved.json")
        mlflow.log_text("\n".join(pip_requirements()) + "\n", "environment_pins.txt")

        # The model: both horizons in one pyfunc, saved locally and logged.
        model_dir = tmp_dir / "model_files"
        model_dir.mkdir()
        artifacts = write_model_files(results, len(params["cities"]), model_dir)
        example = results[min(results)]["eval_example"][FEATURE_COLUMNS].copy()
        example.insert(0, "horizon_h", 1)
        example = example.astype({c: "int64" for c in INT_COLUMNS})
        kwargs = {
            "python_model": str(MODEL_FILE),
            "artifacts": artifacts,
            "signature": model_signature(),
            "pip_requirements": pip_requirements(),
            "input_example": example,
        }
        if candidate_dir.exists():
            shutil.rmtree(candidate_dir)
        candidate_dir.parent.mkdir(parents=True, exist_ok=True)
        mlflow.pyfunc.save_model(path=str(candidate_dir), **kwargs)
        info = mlflow.pyfunc.log_model(name="model", **kwargs)
        return run.info.run_id, info.model_uri


def run_train(params: dict[str, Any]) -> dict[str, int]:
    """Train, score, log, and write reports/train_metrics.json."""
    paths = params["paths"]
    reports = Path(paths["reports_dir"])
    train_path = Path(paths["features_dir"]) / "train.parquet"
    df = load_features(train_path)
    results = {h: fit_horizon(df, h, params) for h in HORIZONS}
    summary = summarize(results)
    versions = {
        "git_commit": git_commit(),
        "git_dirty": git_dirty(),
        "dvc_data_md5": dvc_raw_md5(paths["raw_dvc"]),
        "features_md5": parquet_data_md5(train_path),
    }
    candidate_dir = Path(paths["models_dir"]) / "candidate"
    run_id, model_uri = log_run(
        params, results, summary, versions, reports, candidate_dir
    )

    cutoff = pd.Timestamp(params["cutoff"])
    doc = {
        "run_id": run_id,
        "model_uri": model_uri,
        "experiment": params["train"]["experiment"],
        **versions,
        "cutoff": params["cutoff"],
        "eval_window": {
            "start_exclusive": str(
                cutoff - pd.Timedelta(days=params["eval_window_days"])
            ),
            "end": str(cutoff),
        },
        "mean_mae": summary["mean_mae"],
        "ratio_to_best_baseline": {
            f"{h}h": v for h, v in summary["ratio_to_best_baseline"].items()
        },
        "horizons": {
            f"{h}h": {
                "n_train": r["n_train"],
                "n_eval": r["n_eval"],
                "metrics": r["metrics"],
                "best_baseline": r["best_baseline"],
                "high_value": r["high_value"],
            }
            for h, r in results.items()
        },
    }
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "train_metrics.json").write_text(
        json.dumps(doc, indent=2), encoding="utf-8"
    )
    log.info("Logged MLflow run %s", run_id)
    return {"rows_in": len(df), "rows_out": sum(r["n_train"] for r in results.values())}


def main() -> None:
    """Command-line entry point used by dvc.yaml and MLproject."""
    configure_logging()
    load_env()
    params = load_params()
    run_stage("train", lambda: run_train(params), params)


if __name__ == "__main__":
    main()
