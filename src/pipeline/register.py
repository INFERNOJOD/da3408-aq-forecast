"""Stage 7 of the DVC pipeline: register the candidate if the gate passed.

Passed: a new registry version is created from the candidate's MLflow model, the
``champion`` alias moves to it, and the old champion becomes ``previous``.
Rejected: nothing is registered and the champion stays. The training run is
tagged ``promotion=rejected`` with the reasons, so the rejection can be found in
MLflow and in the console.

Run: ``python -m src.pipeline.register``  ->  reports/register.json
"""

import json
from pathlib import Path
from typing import Any

import mlflow

from src.common.config import load_env, load_params
from src.common.errors import DataValidationError
from src.common.logging_setup import configure_logging, get_logger
from src.common.stage_runner import run_stage
from src.pipeline.registry import ModelRegistryClient

log = get_logger(__name__)


def read_json(path: Path, producer: str) -> dict[str, Any]:
    """Read a JSON report or fail with a hint about which stage makes it."""
    if not path.is_file():
        raise DataValidationError(f"{path} not found. Run {producer} first.")
    return json.loads(path.read_text(encoding="utf-8"))


def register(
    params: dict[str, Any],
    gate: dict[str, Any],
    train_doc: dict[str, Any],
    eval_doc: dict[str, Any],
    registry: ModelRegistryClient,
) -> dict[str, Any]:
    """Promote or reject; return the register.json document."""
    run_id = train_doc["run_id"]
    if gate["candidate_run_id"] != run_id or eval_doc["candidate"]["run_id"] != run_id:
        raise DataValidationError("gate.json, eval.json and train_metrics.json differ")
    old = registry.champion_version()
    doc: dict[str, Any] = {
        "promoted": gate["passed"],
        "version": None,
        "champion_before": old,
        "mlflow_run_id": run_id,
        "reasons": gate["reasons"],
        "cutoff": params["cutoff"],
        "git_commit": train_doc["git_commit"],
    }
    if gate["passed"]:
        hs = eval_doc["candidate"]["horizons"]
        tags = {
            "cutoff": params["cutoff"],
            "git_commit": train_doc["git_commit"],
            "dvc_data_md5": train_doc["dvc_data_md5"],
            "mae_1h": f"{hs['1h']['mae']:.4f}",
            "mae_24h": f"{hs['24h']['mae']:.4f}",
            "model_1h": hs["1h"]["model"],
            "model_24h": hs["24h"]["model"],
        }
        doc["version"] = registry.promote(train_doc["model_uri"], run_id, tags)
        outcome = {"promotion": "promoted", "registry_version": doc["version"]}
    else:
        outcome = {
            "promotion": "rejected",
            "rejected_reasons": "; ".join(gate["reasons"]),
        }
    with mlflow.start_run(run_id=run_id):
        mlflow.set_tags(outcome)
        mlflow.log_metrics(
            {
                "eval_candidate_mean_mae": gate["candidate_mean_mae"],
                **(
                    {}
                    if gate["champion_mean_mae"] is None
                    else {"eval_champion_mean_mae": gate["champion_mean_mae"]}
                ),
            }
        )
    log.info("Candidate %s: %s", run_id[:8], outcome["promotion"])
    return doc


def run_register(params: dict[str, Any]) -> dict[str, int]:
    """Read the reports, promote or reject, and write reports/register.json."""
    reports = Path(params["paths"]["reports_dir"])
    gate = read_json(reports / "gate.json", "test")
    eval_doc = read_json(reports / "eval.json", "evaluate")
    train_doc = read_json(reports / "train_metrics.json", "train")
    registry = ModelRegistryClient(params["promotion"]["model_name"])
    doc = register(params, gate, train_doc, eval_doc, registry)
    (reports / "register.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return {"rows_in": 1, "rows_out": 1}


def main() -> None:
    """Command-line entry point used by dvc.yaml."""
    configure_logging()
    load_env()
    params = load_params()
    run_stage("register", lambda: run_register(params), params)


if __name__ == "__main__":
    main()
