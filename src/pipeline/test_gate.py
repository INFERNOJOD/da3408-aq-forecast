"""Stage 6 of the DVC pipeline: the promotion rule (docs/HLD.md, "Promotion rule").

A candidate passes only if both hold:

1. For every horizon, the served model (the better of Ridge and LightGBM) has an
   MAE within ``max_ratio_to_baseline`` (1.02) times the best baseline's MAE.
   The limit is not relaxed, also not for the first model.
2. If a champion exists, the candidate's mean MAE over the horizons is strictly
   lower than the champion's on the same window. A tie is not an improvement.

A rejection is a normal result, not a pipeline failure: the stage succeeds and
writes ``passed: false`` with the reasons.

The module is named ``test_gate`` so that pytest does not collect it.

Run: ``python -m src.pipeline.test_gate``  ->  reports/gate.json
"""

import json
from pathlib import Path
from typing import Any

from src.common.config import load_env, load_params
from src.common.errors import DataValidationError
from src.common.logging_setup import configure_logging, get_logger
from src.common.stage_runner import run_stage

log = get_logger(__name__)


def decide(eval_doc: dict[str, Any], max_ratio: float) -> dict[str, Any]:
    """Apply the rule to an eval.json document; return the gate.json document."""
    reasons: list[str] = []
    ratios: dict[str, float] = {}
    candidate = eval_doc["candidate"]
    for name, h in candidate["horizons"].items():
        ratio = h["mae"] / h["best_baseline"]["mae"]
        ratios[name] = ratio
        if ratio > max_ratio:
            reasons.append(
                f"{name}: {h['model']} MAE {h['mae']:.2f} is {ratio:.3f} times the "
                f"best baseline ({h['best_baseline']['name']} "
                f"{h['best_baseline']['mae']:.2f}), limit {max_ratio}"
            )
    champion = eval_doc["champion"]
    if champion is not None and not candidate["mean_mae"] < champion["mean_mae"]:
        reasons.append(
            f"mean MAE {candidate['mean_mae']:.3f} is not lower than champion "
            f"v{champion['version']} {champion['mean_mae']:.3f} on the same window"
        )
    return {
        "passed": not reasons,
        "reasons": reasons,
        "first_model": champion is None,
        "ratio_to_best_baseline": ratios,
        "max_ratio": max_ratio,
        "candidate_mean_mae": candidate["mean_mae"],
        "champion_mean_mae": None if champion is None else champion["mean_mae"],
        "candidate_run_id": candidate["run_id"],
    }


def run_gate(params: dict[str, Any]) -> dict[str, int]:
    """Read eval.json, decide, and write reports/gate.json."""
    reports = Path(params["paths"]["reports_dir"])
    path = reports / "eval.json"
    if not path.is_file():
        raise DataValidationError(f"{path} not found. Run evaluate first.")
    gate = decide(
        json.loads(path.read_text(encoding="utf-8")),
        params["promotion"]["max_ratio_to_baseline"],
    )
    (reports / "gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
    if gate["passed"]:
        log.info("Gate passed: the candidate may be promoted")
    else:
        log.warning("Gate rejected the candidate: %s", "; ".join(gate["reasons"]))
    return {"rows_in": 1, "rows_out": 1}


def main() -> None:
    """Command-line entry point used by dvc.yaml."""
    configure_logging()
    load_env()
    params = load_params()
    run_stage("test", lambda: run_gate(params), params)


if __name__ == "__main__":
    main()
