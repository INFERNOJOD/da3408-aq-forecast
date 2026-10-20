"""Pipeline runs and stage status, read from ``reports/runs.jsonl``.

Every stage appends one line to that file (src/common/stage_runner.py). A run is
all lines with the same ``run_id``.
"""

import json
from pathlib import Path

from src.common.logging_setup import get_logger

log = get_logger(__name__)

# The DVC DAG, in order, with each stage's dependencies (dvc.yaml).
STAGES = {
    "ingest": [],
    "validate": ["ingest"],
    "features": ["validate"],
    "train": ["features"],
    "evaluate": ["train"],
    "test": ["evaluate"],
    "register": ["test"],
}


def read_records(reports_dir: Path) -> list[dict]:
    """All stage records, oldest first. Unreadable lines are skipped and logged."""
    path = Path(reports_dir) / "runs.jsonl"
    if not path.exists():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("Skipping bad line %d in %s", number, path)
    return records


def _read_json(path: Path) -> dict:
    """Read a small JSON report, or {} if it is missing or broken."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _group(records: list[dict]) -> dict[str, list[dict]]:
    """Group records by run id, keeping the order of first appearance."""
    runs: dict[str, list[dict]] = {}
    for rec in records:
        runs.setdefault(rec["run_id"], []).append(rec)
    return runs


def stages(reports_dir: Path) -> dict:
    """Return the body of GET /pipeline/stages for the newest run."""
    runs = _group(read_records(reports_dir))
    run_id = next(reversed(runs), None)
    by_stage = {r["stage"]: r for r in runs.get(run_id, [])}
    out = []
    for name, deps in STAGES.items():
        rec = by_stage.get(name)
        out.append(
            {
                "name": name,
                "deps": deps,
                "status": rec["status"] if rec else "not_run",
                "duration_s": rec["duration_s"] if rec else None,
                "rows_out": rec["rows_out"] if rec else None,
                "rows_per_sec": rec["rows_per_sec"] if rec else None,
            }
        )
    return {"run_id": run_id, "stages": out}


def runs(reports_dir: Path, limit: int) -> list[dict]:
    """Return the body of GET /pipeline/runs, newest run first.

    ``promoted`` and ``mlflow_run_id`` are only known for the newest run when it
    ran the register stage, from ``register.json``; ``runs.jsonl`` does not store them.
    """
    grouped = _group(read_records(reports_dir))
    register = _read_json(Path(reports_dir) / "register.json")
    newest = next(reversed(grouped), None)
    out = []
    for run_id in list(reversed(grouped))[:limit]:
        recs = grouped[run_id]
        failed = next((r for r in recs if r["status"] == "failed"), None)
        # runs.jsonl cannot say "still running", and DVC skips unchanged stages,
        # so a run without a failed stage counts as a success.
        status = "failed" if failed else "success"
        # register.json belongs to the newest run, and only if that run registered.
        latest = run_id == newest and any(r["stage"] == "register" for r in recs)
        out.append(
            {
                "run_id": run_id,
                "trigger": recs[0].get("trigger", "manual"),
                "status": status,
                "started_at": recs[0]["started_at"],
                "duration_s": round(sum(r["duration_s"] for r in recs), 1),
                "cutoff": recs[0].get("cutoff"),
                "failed_stage": failed["stage"] if failed else None,
                "error": failed.get("error") if failed else None,
                "git_commit": recs[0].get("git_commit"),
                "mlflow_run_id": register.get("mlflow_run_id") if latest else None,
                "promoted": register.get("promoted") if latest else None,
            }
        )
    return out
