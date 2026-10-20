"""Stage 5 of the DVC pipeline: score the candidate and the champion together.

Both models are loaded as MLflow packages (the same code path the model server
uses) and predict the same evaluation rows: the last ``eval_window_days`` before
the cutoff, per horizon. Using one window for both is what makes the comparison
fair. The baselines come from the train stage, which scored them on these rows.

If there is no champion yet (the first model), only the candidate is scored.

Run: ``python -m src.pipeline.evaluate``  ->  reports/eval.json
"""

import json
from pathlib import Path
from typing import Any

import mlflow.pyfunc
import numpy as np
import pandas as pd

from src.common.config import load_env, load_params
from src.common.errors import DataValidationError
from src.common.logging_setup import configure_logging, get_logger
from src.common.schema import FEATURE_COLUMNS, FEATURES, HORIZONS
from src.common.stage_runner import run_stage
from src.pipeline import modeling
from src.pipeline.registry import ModelRegistryClient
from src.pipeline.train import INT_COLUMNS, load_features

log = get_logger(__name__)


def model_input(rows: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Build the request the model package expects (docs/LLD.md, section 4)."""
    frame = rows[FEATURE_COLUMNS].copy()
    frame.insert(0, "horizon_h", horizon)
    ints = {c: "int64" for c in INT_COLUMNS}
    floats = {c: "float64" for c in frame.columns if c not in INT_COLUMNS}
    return frame[FEATURES].astype({**ints, **floats})


def score_package(model: Any, windows: dict[int, pd.DataFrame]) -> dict[int, dict]:
    """MAE and RMSE of a loaded model package on each horizon's rows."""
    out = {}
    for horizon, rows in windows.items():
        pred = model.predict(model_input(rows, horizon))["pm25"].to_numpy()
        out[horizon] = modeling.error_metrics(rows[HORIZONS[horizon]].to_numpy(), pred)
    return out


def mean_mae(scores: dict[int, dict]) -> float:
    """Mean of the per-horizon MAE values."""
    return float(np.mean([s["mae"] for s in scores.values()]))


def evaluate(
    params: dict[str, Any], train_doc: dict[str, Any], df: pd.DataFrame, registry: Any
) -> dict[str, Any]:
    """Return the eval.json document for the candidate (and the champion)."""
    if train_doc["cutoff"] != params["cutoff"]:
        raise DataValidationError(
            f"train_metrics.json is for cutoff {train_doc['cutoff']} but params "
            f"say {params['cutoff']}. Run train again."
        )
    windows = {
        h: modeling.split_for_horizon(
            df, h, params["cutoff"], params["eval_window_days"]
        )[1]
        for h in HORIZONS
    }
    candidate_dir = Path(params["paths"]["models_dir"]) / "candidate"
    scores = score_package(mlflow.pyfunc.load_model(str(candidate_dir)), windows)
    doc: dict[str, Any] = {
        "cutoff": params["cutoff"],
        "eval_window": train_doc["eval_window"],
        "candidate": {
            "run_id": train_doc["run_id"],
            "model_uri": train_doc["model_uri"],
            "mean_mae": mean_mae(scores),
            "horizons": {
                f"{h}h": {
                    **scores[h],
                    "model": train_doc["horizons"][f"{h}h"]["chosen"]["model"],
                    "best_baseline": train_doc["horizons"][f"{h}h"]["best_baseline"],
                }
                for h in HORIZONS
            },
        },
        "champion": None,
    }
    version = registry.champion_version()
    if version is None:
        log.info("No champion in the registry: scoring the candidate alone")
        return doc
    champion = mlflow.pyfunc.load_model(registry.champion_uri())
    champ_scores = score_package(champion, windows)
    doc["champion"] = {
        "version": version,
        "mean_mae": mean_mae(champ_scores),
        "horizons": {f"{h}h": champ_scores[h] for h in HORIZONS},
    }
    log.info(
        "Mean MAE on the same window: candidate %.3f, champion v%s %.3f",
        doc["candidate"]["mean_mae"],
        version,
        doc["champion"]["mean_mae"],
    )
    return doc


def run_evaluate(params: dict[str, Any]) -> dict[str, int]:
    """Read the inputs, score, and write reports/eval.json."""
    paths = params["paths"]
    reports = Path(paths["reports_dir"])
    train_path = reports / "train_metrics.json"
    if not train_path.is_file():
        raise DataValidationError(f"{train_path} not found. Run train first.")
    train_doc = json.loads(train_path.read_text(encoding="utf-8"))
    df = load_features(Path(paths["features_dir"]) / "train.parquet")
    registry = ModelRegistryClient(params["promotion"]["model_name"])
    doc = evaluate(params, train_doc, df, registry)
    (reports / "eval.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    rows = sum(h["n"] for h in doc["candidate"]["horizons"].values())
    return {"rows_in": rows, "rows_out": rows}


def main() -> None:
    """Command-line entry point used by dvc.yaml."""
    configure_logging()
    load_env()
    params = load_params()
    run_stage("evaluate", lambda: run_evaluate(params), params)


if __name__ == "__main__":
    main()
