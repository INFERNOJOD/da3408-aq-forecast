"""The ops runner: picks up retrain requests and runs the pipeline (docs/HLD.md).

The backend never trains. It writes ``ops/requests/<id>.json``; this runner, on
the host, handles one request at a time:

1. mark it ``running``,
2. stop the frontend and Grafana, so the batch never runs next to the full
   serve stack (CLAUDE.md), and check there is enough free memory for Spark,
3. move ``cutoff`` in params.yaml to the request's simulated time, so the
   retrain sees the replayed hours up to then,
4. hand the drift numbers to the train stage (``reports/drift_trigger.json``),
5. run ``dvc repro`` with ``PIPELINE_TRIGGER`` and one ``PIPELINE_RUN_ID``,
   then start the frontend and Grafana again, whether the run passed or not,
6. read ``reports/register.json``. If the candidate was promoted, wait until the
   model server serves the new version and answers a test forecast (smoke
   check). If it does not, roll back to the previous champion.

Final status: ``done`` (promoted or rejected by the gate), ``failed`` or
``rolled_back``. Run: ``python -m src.ops.runner`` (``--once`` for one pass).
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.backend.model_client import ModelServerClient, ModelUnavailableError
from src.common.config import PROJECT_ROOT, load_env, load_params
from src.common.errors import RegistryError
from src.common.logging_setup import configure_logging, get_logger
from src.common.schema import FEATURE_COLUMNS
from src.pipeline.registry import ModelRegistryClient

log = get_logger(__name__)

CUTOFF_LINE = re.compile(r'^cutoff: "([^"]*)"', re.MULTILINE)
CUTOFF_FORMAT = "%Y-%m-%d %H:%M:%S"


class RequestError(Exception):
    """A request that cannot be run; the message goes into the request file."""


def read_cutoff(params_path: Path) -> str:
    """Return the ``cutoff`` value in params.yaml."""
    match = CUTOFF_LINE.search(params_path.read_text(encoding="utf-8"))
    if not match:
        raise RequestError(f"No cutoff line in {params_path}")
    return match.group(1)


def write_cutoff(params_path: Path, cutoff: str) -> None:
    """Replace the cutoff value in params.yaml, keeping its comment and layout."""
    text = params_path.read_text(encoding="utf-8")
    params_path.write_text(
        CUTOFF_LINE.sub(f'cutoff: "{cutoff}"', text, count=1), encoding="utf-8"
    )


def new_cutoff(requested: str, current: str, replay_end: str) -> str:
    """Validate the request's cutoff and return it in params.yaml format.

    It must lie after the current cutoff (otherwise the retrain sees no new
    data) and not after the end of the replay.
    """
    try:
        value = datetime.fromisoformat(requested).replace(minute=0, second=0)
    except (TypeError, ValueError) as exc:
        raise RequestError(f"Bad cutoff {requested!r}") from exc
    if value <= datetime.fromisoformat(current):
        raise RequestError(f"Cutoff {value} is not after the current cutoff {current}")
    if value > datetime.fromisoformat(replay_end):
        raise RequestError(f"Cutoff {value} is after the replay end {replay_end}")
    return value.strftime(CUTOFF_FORMAT)


def available_mb() -> float:
    """MemAvailable from /proc/meminfo in MB (inf where it cannot be read)."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return math.inf


def run_dvc_repro(env: dict[str, str], log_path: Path, timeout_s: int) -> int:
    """Run ``dvc repro`` in the project folder; output goes to ``log_path``."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as fh:
        try:
            done = subprocess.run(
                ["dvc", "repro"],
                cwd=PROJECT_ROOT,
                env={**os.environ, **env},
                stdout=fh,
                stderr=subprocess.STDOUT,
                timeout=timeout_s,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            fh.write(f"\nrunner: {exc}\n")
            return -1
    return done.returncode


def run_compose(args: list[str]) -> str:
    """Run ``docker compose --profile serve <args>`` here; return its stdout.

    Raises RuntimeError when docker is missing, times out or fails.
    """
    try:
        done = subprocess.run(
            ["docker", "compose", "--profile", "serve", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"docker compose {' '.join(args)}: {exc}") from exc
    if done.returncode != 0:
        raise RuntimeError(
            f"docker compose {' '.join(args)} exited with {done.returncode}: "
            f"{done.stderr.strip()[-200:]}"
        )
    return done.stdout


class ServicePause:
    """Stops some serve containers for the batch and starts them again after.

    On 8 GB the Spark batch must not run next to the full serve stack. The
    frontend and Grafana are the two nobody needs while a model trains. The
    backend, model server, MLflow and the monitoring keep running, so the
    retrain can be watched in Prometheus and the new model can be smoke-checked.

    Only containers that were running are stopped, and exactly the ones that
    stopped are started again, so a service the operator had stopped on purpose
    stays stopped. A docker error never fails the request: the memory check
    after the pause still decides whether the batch may start.
    """

    def __init__(
        self,
        services: list[str],
        compose: Callable[[list[str]], str] = run_compose,
    ) -> None:
        """``services`` are compose service names, such as ``frontend``."""
        self.services = list(services)
        self._compose = compose

    def _running(self) -> set[str]:
        return set(self._compose(["ps", "--status", "running", "--services"]).split())

    def pause(self) -> list[str]:
        """Stop the configured services that run; return the ones now stopped."""
        if not self.services:
            return []
        try:
            before = self._running()
            names = [s for s in self.services if s in before]
            if not names:
                return []
            self._compose(["stop", *names])
            # Compared before and after: if compose also stops a dependent
            # container (Compose v5.6 leaves the TLS proxy up), it is restarted too.
            stopped = sorted(before - self._running())
        except RuntimeError as exc:
            log.warning("Could not stop %s (%s)", ", ".join(self.services), exc)
            return []
        log.info("Stopped %s for the batch", ", ".join(stopped))
        return stopped

    def resume(self, names: list[str]) -> None:
        """Start the services ``pause`` stopped. Errors are logged, not raised."""
        if not names:
            return
        try:
            self._compose(["start", *names])
            log.info("Started %s again", ", ".join(names))
        except RuntimeError as exc:
            log.error("Could not start %s again: %s", ", ".join(names), exc)


class SmokeCheck:
    """Asks the model server for a forecast until the expected version answers."""

    def __init__(
        self,
        client: ModelServerClient,
        sample: dict,
        timeout_s: float,
        poll_s: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        """``sample`` is one feature row (``FEATURE_COLUMNS``)."""
        self.client, self.sample = client, sample
        self.timeout_s, self.poll_s = timeout_s, poll_s
        self._sleep, self._now = sleep, now

    def __call__(self, version: str) -> tuple[bool, str]:
        """Return (passed, message). Passed means the right version, a sane value."""
        deadline = self._now() + self.timeout_s
        last = "no answer"
        while True:
            try:
                pred = self.client.predict([{**self.sample, "horizon_h": 1}])[0]
                served = str(pred.get("model_version"))
                value = float(pred["pm25"])
                if served == version and math.isfinite(value) and value >= 0:
                    return True, f"version {version} answered {value}"
                last = f"served version {served}, value {value}"
            except (ModelUnavailableError, KeyError, TypeError, ValueError) as exc:
                last = str(exc)
            if self._now() >= deadline:
                return False, f"smoke check failed after {self.timeout_s:.0f}s: {last}"
            self._sleep(self.poll_s)


class OpsRunner:
    """Processes request files one at a time (oldest first)."""

    def __init__(
        self,
        ops_dir: Path,
        params_path: Path,
        reports_dir: Path,
        replay_end: str,
        registry: ModelRegistryClient,
        smoke: Callable[[str], tuple[bool, str]],
        run_pipeline: Callable[[dict[str, str], Path], int],
        min_free_mb: float = 2500,
        free_mb: Callable[[], float] = available_mb,
        now: Callable[[], datetime] = datetime.now,
        services: ServicePause | None = None,
    ) -> None:
        """Keep the collaborators; tests pass fakes for the pipeline and checks.

        ``services`` stops and restarts containers around the batch; None
        leaves every container alone.
        """
        self.requests = Path(ops_dir) / "requests"
        self.logs = Path(ops_dir) / "logs"
        self.params_path, self.reports = Path(params_path), Path(reports_dir)
        self.replay_end = replay_end
        self.registry, self.smoke, self.run_pipeline = registry, smoke, run_pipeline
        self.min_free_mb, self.free_mb, self._now = min_free_mb, free_mb, now
        self.services = services or ServicePause([])

    def _save(self, path: Path, record: dict) -> None:
        """Write the request atomically, so the backend never reads half a file."""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _stamp(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def pending(self) -> list[Path]:
        """Queued request files, oldest first."""
        out = []
        for path in sorted(self.requests.glob("*.json")):
            try:
                if (
                    json.loads(path.read_text(encoding="utf-8")).get("status")
                    == "queued"
                ):
                    out.append(path)
            except (OSError, ValueError):
                log.warning("Unreadable request file %s", path)
        return out

    def recover(self) -> int:
        """Mark requests left ``running`` by a crashed runner as failed."""
        count = 0
        for path in sorted(self.requests.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if record.get("status") == "running":
                record.update(
                    status="failed",
                    error="runner restarted while this request was running",
                    finished_at=self._stamp(),
                )
                self._save(path, record)
                count += 1
        return count

    def process(self, path: Path) -> dict:
        """Run one request to its final status and return the updated record."""
        record = json.loads(path.read_text(encoding="utf-8"))
        run_id = self._now().strftime("%Y%m%d-%H%M%S")
        record.update(status="running", started_at=self._stamp(), run_id=run_id)
        self._save(path, record)
        log.info("Request %s: running as pipeline run %s", record["request_id"], run_id)
        try:
            record.update(self._run(record, run_id))
        except RequestError as exc:
            record.update(status="failed", error=str(exc))
            log.error("Request %s failed: %s", record["request_id"], exc)
        record["finished_at"] = self._stamp()
        self._save(path, record)
        log.info("Request %s finished: %s", record["request_id"], record["status"])
        return record

    def _run(self, record: dict, run_id: str) -> dict:
        """Run the steps of ``process``. Raises RequestError when a step fails."""
        current = read_cutoff(self.params_path)
        cutoff = new_cutoff(record.get("cutoff"), current, self.replay_end)

        # The batch only starts with the frontend and Grafana stopped, and they
        # come back as soon as dvc repro ends, also when it fails.
        paused = self.services.pause()
        record["paused"] = paused
        try:
            free = self.free_mb()
            if free < self.min_free_mb:
                raise RequestError(
                    f"only {free:.0f} MB free after stopping "
                    f"{', '.join(paused) or 'nothing'}; "
                    f"the batch needs {self.min_free_mb:.0f} MB"
                )
            write_cutoff(self.params_path, cutoff)
            log.info("cutoff %s -> %s", current, cutoff)

            trigger = record.get("trigger") or "manual"
            trigger_file = self.reports / "drift_trigger.json"
            if trigger == "drift_alert" and record.get("drift"):
                trigger_file.write_text(json.dumps(record["drift"]), encoding="utf-8")
            env = {"PIPELINE_TRIGGER": trigger, "PIPELINE_RUN_ID": run_id}
            try:
                code = self.run_pipeline(env, self.logs / f"{record['request_id']}.log")
            finally:
                trigger_file.unlink(missing_ok=True)
        finally:
            self.services.resume(paused)
        if code != 0:
            raise RequestError(
                f"dvc repro exited with {code}; {self._stage_error(run_id)}"
            )

        result = json.loads(
            (self.reports / "register.json").read_text(encoding="utf-8")
        )
        if result.get("cutoff") != cutoff:
            raise RequestError("register.json is not from this run (cutoff differs)")
        out = {
            "cutoff": cutoff,
            "promoted": bool(result.get("promoted")),
            "version": result.get("version"),
            "mlflow_run_id": result.get("mlflow_run_id"),
            "reasons": result.get("reasons", []),
        }
        if not out["promoted"]:
            log.info("Candidate rejected: %s", "; ".join(out["reasons"]))
            return {**out, "status": "done"}

        passed, message = self.smoke(str(out["version"]))
        out["smoke"] = message
        if passed:
            return {**out, "status": "done"}
        log.error(
            "New champion v%s failed the smoke check: %s", out["version"], message
        )
        try:
            old, new = self.registry.rollback()
        except RegistryError as exc:
            raise RequestError(f"{message}; rollback failed too: {exc}") from exc
        log.warning("Auto-rollback: champion %s -> %s", old, new)
        return {**out, "status": "rolled_back", "rolled_back_to": new}

    def _stage_error(self, run_id: str) -> str:
        """Return the error of this run's failed stage, from runs.jsonl."""
        try:
            lines = (
                (self.reports / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            )
        except OSError:
            return "no stage record"
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("run_id") == run_id and rec.get("status") == "failed":
                return f"stage {rec['stage']}: {rec.get('error')}"
        return "no failed stage recorded (see the run log)"

    def run_once(self) -> int:
        """Process every queued request; return how many were processed."""
        paths = self.pending()
        for path in paths:
            self.process(path)
        return len(paths)


def sample_row(serving_path: Path) -> dict:
    """One complete feature row for the smoke check (the first hour of Delhi)."""
    frame = pd.read_parquet(serving_path, columns=["City", *FEATURE_COLUMNS])
    row = frame.dropna().iloc[0]
    return {c: row[c].item() for c in FEATURE_COLUMNS}


def build(params: dict) -> OpsRunner:
    """Create the runner from params.yaml and the environment (docs/LLD.md §8)."""
    paths = params["paths"]
    client = ModelServerClient(
        os.environ.get("MODEL_SERVER_URL", "http://localhost:5001")
    )
    smoke = SmokeCheck(
        client,
        sample_row(PROJECT_ROOT / paths["features_dir"] / "serving.parquet"),
        float(os.environ.get("SMOKE_TIMEOUT_S", "180")),
    )
    timeout = int(os.environ.get("RUN_TIMEOUT_S", "3600"))
    return OpsRunner(
        ops_dir=Path(os.environ.get("OPS_DIR", PROJECT_ROOT / "ops")),
        params_path=PROJECT_ROOT / "params.yaml",
        reports_dir=PROJECT_ROOT / paths["reports_dir"],
        replay_end=params["replay"]["end"],
        registry=ModelRegistryClient(params["promotion"]["model_name"]),
        smoke=smoke,
        run_pipeline=lambda env, log_path: run_dvc_repro(env, log_path, timeout),
        min_free_mb=float(os.environ.get("RUNNER_MIN_FREE_MB", "2500")),
        services=ServicePause(
            os.environ.get("RUNNER_PAUSE_SERVICES", "frontend grafana").split()
        ),
    )


def main(argv: list[str] | None = None) -> int:
    """Poll for requests (or one pass with ``--once``)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument(
        "--poll", type=float, default=10.0, help="seconds between polls"
    )
    args = parser.parse_args(argv)
    configure_logging()
    load_env()
    runner = build(load_params())
    runner.requests.mkdir(parents=True, exist_ok=True)
    if runner.recover():
        log.warning("Marked interrupted requests as failed")
    log.info("Ops runner watching %s", runner.requests)
    while True:
        runner.run_once()
        if args.once:
            return 0
        time.sleep(args.poll)


if __name__ == "__main__":
    sys.exit(main())
