"""Run a pipeline stage and record how it went.

Every stage writes one JSON line to reports/runs.jsonl (see docs/LLD.md, section
6). The backend reads that file to show runs in the pipeline console. Timing
numbers are also pushed to the Prometheus Pushgateway when PUSHGATEWAY_URL is set.
"""

import json
import os
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from prometheus_client import CollectorRegistry, Gauge, pushadd_to_gateway

from src.common.errors import AQError, PipelineStageError
from src.common.logging_setup import get_logger

log = get_logger(__name__)

RUNS_FILE = "runs.jsonl"
PUSH_TIMEOUT_S = 5


def new_run_id() -> str:
    """Return the current run id: PIPELINE_RUN_ID env var or a timestamp."""
    return os.environ.get("PIPELINE_RUN_ID") or datetime.now().strftime("%Y%m%d-%H%M%S")


def current_git_commit() -> str:
    """Return the short git commit hash, or 'unknown' if git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        log.warning("Could not read git commit hash")
        return "unknown"


def rows_per_second(rows: int | None, duration_s: float) -> float | None:
    """Return throughput, or None when rows is unknown or time is zero."""
    if rows is None or duration_s <= 0:
        return None
    return round(rows / duration_s, 1)


def push_metrics(record: dict[str, Any], url: str) -> bool:
    """Push one stage record to the Pushgateway. Returns True on success.

    A monitoring outage must never fail the pipeline, so errors are logged
    and swallowed.
    """
    registry = CollectorRegistry()
    stage = record["stage"]
    ok = 1 if record["status"] == "success" else 0
    Gauge(
        "aq_stage_duration_seconds",
        "Stage wall-clock time",
        ["stage", "run_id"],
        registry=registry,
    ).labels(stage, record["run_id"]).set(record["duration_s"])
    Gauge(
        "aq_stage_status",
        "1 = success, 0 = failed",
        ["stage"],
        registry=registry,
    ).labels(stage).set(ok)
    if record["rows_per_sec"] is not None:
        Gauge(
            "aq_stage_rows_per_second",
            "Rows processed per second",
            ["stage"],
            registry=registry,
        ).labels(stage).set(record["rows_per_sec"])
    if ok:
        Gauge(
            "aq_pipeline_last_success_timestamp",
            "Unix time of last successful stage",
            registry=registry,
        ).set(time.time())
    try:
        pushadd_to_gateway(
            url,
            job="aq_pipeline",
            registry=registry,
            grouping_key={"instance": stage},
            timeout=PUSH_TIMEOUT_S,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - any push error is non-fatal
        log.warning("Pushgateway not reachable (%s); metrics not pushed", exc)
        return False


def write_record(record: dict[str, Any], reports_dir: str | Path) -> None:
    """Append the record to runs.jsonl and save the latest one per stage."""
    reports = Path(reports_dir)
    (reports / "stage_metrics").mkdir(parents=True, exist_ok=True)
    with (reports / RUNS_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    latest = reports / "stage_metrics" / f"{record['stage']}.json"
    latest.write_text(json.dumps(record, indent=2), encoding="utf-8")


def run_stage(
    stage: str,
    func: Callable[[], dict[str, Any]],
    params: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run ``func`` as pipeline stage ``stage`` and record the outcome.

    ``func`` returns a dict that may contain ``rows_in`` and ``rows_out``.
    On success the full record is returned. On failure the record is saved
    with status "failed" and PipelineStageError is raised.
    """
    reports_dir = params["paths"]["reports_dir"]
    record: dict[str, Any] = {
        "run_id": run_id or new_run_id(),
        "trigger": os.environ.get("PIPELINE_TRIGGER", "manual"),
        "stage": stage,
        "status": "failed",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "duration_s": 0.0,
        "rows_in": None,
        "rows_out": None,
        "rows_per_sec": None,
        "error": None,
        "git_commit": current_git_commit(),
        "cutoff": params.get("cutoff"),
    }
    log.info("Stage '%s' started (run %s)", stage, record["run_id"])
    start = time.perf_counter()
    error: PipelineStageError | None = None
    try:
        result = func() or {}
        record["status"] = "success"
        record["rows_in"] = result.get("rows_in")
        record["rows_out"] = result.get("rows_out")
    except PipelineStageError as exc:
        record["error"] = exc.message
        error = exc
    except AQError as exc:
        record["error"] = str(exc)
        error = PipelineStageError(stage, str(exc))
    except Exception as exc:  # noqa: BLE001 - record any unexpected crash
        log.exception("Stage '%s' crashed", stage)
        record["error"] = f"{type(exc).__name__}: {exc}"
        error = PipelineStageError(stage, record["error"])
    record["duration_s"] = round(time.perf_counter() - start, 3)
    record["rows_per_sec"] = rows_per_second(record["rows_out"], record["duration_s"])

    write_record(record, reports_dir)
    url = os.environ.get("PUSHGATEWAY_URL")
    if url:
        push_metrics(record, url)
    if error is not None:
        log.error("Stage '%s' FAILED: %s", stage, record["error"])
        raise error from None
    log.info(
        "Stage '%s' done in %.1fs (%s rows, %s rows/s)",
        stage,
        record["duration_s"],
        record["rows_out"],
        record["rows_per_sec"],
    )
    return record
