"""Push the latest record of every pipeline stage to the Pushgateway again.

Each stage pushes its own numbers when it finishes. If the Pushgateway was not
running then (the batch ran on its own, or before Stage 14), Grafana has
nothing to show. This re-sends ``reports/stage_metrics/<stage>.json``, the
numbers that run really measured; nothing is recomputed.

Usage:
    python -m scripts.push_stage_metrics [--url http://localhost:19091]
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from src.common.logging_setup import configure_logging, get_logger
from src.common.stage_runner import push_metrics

log = get_logger(__name__)
REPORTS = Path(__file__).resolve().parents[1] / "reports" / "stage_metrics"


def end_time(record: dict) -> float:
    """Unix time the stage finished: its start time plus its duration."""
    start = datetime.fromisoformat(record["started_at"]).timestamp()
    return start + float(record["duration_s"])


def main(argv: list[str] | None = None) -> int:
    """Push every stage record found. Returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--url", default=os.environ.get("PUSHGATEWAY_URL", "http://localhost:19091")
    )
    parser.add_argument("--dir", type=Path, default=REPORTS)
    args = parser.parse_args(argv)
    configure_logging()
    files = sorted(args.dir.glob("*.json"))
    if not files:
        log.error("No stage records in %s", args.dir)
        return 1
    failed = 0
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            ok = push_metrics(record, args.url, success_time=end_time(record))
        except (OSError, ValueError, KeyError) as exc:
            log.error("Skipping %s: %s", path.name, exc)
            ok = False
        if ok:
            log.info("Pushed %s (run %s)", record["stage"], record["run_id"])
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
