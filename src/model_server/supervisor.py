"""Run ``mlflow models serve`` for the ``champion`` alias and follow the alias.

The watcher polls the registry. When ``champion`` points to a new version it
downloads the package, starts a second MLflow process on the spare port, waits
until ``/ping`` answers, switches the proxy to it and only then stops the old
one. If the new model does not start, the old one keeps serving and the next
poll tries again. This is what makes a promotion or a rollback take effect
without a restart of the container (docs/HLD.md, "Model reload").
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import mlflow
import requests

from src.common.errors import AQError
from src.common.logging_setup import get_logger
from src.model_server.proxy import Upstream
from src.pipeline.registry import ModelRegistryClient

log = get_logger(__name__)

PORTS = (5002, 5003)  # internal MLflow ports; the new model uses the spare one
START_TIMEOUT_S = 90


class ModelServerError(AQError):
    """The MLflow process could not be started or did not become ready."""


def download_package(registry: ModelRegistryClient, version: str, dest: Path) -> Path:
    """Download registry version ``version`` into ``dest`` and return the folder."""
    target = dest / f"v{version}"
    target.mkdir(parents=True, exist_ok=True)
    path = mlflow.artifacts.download_artifacts(
        artifact_uri=f"models:/{registry.name}/{version}", dst_path=str(target)
    )
    return Path(path)


def start_mlflow(model_dir: Path, port: int, version: str) -> subprocess.Popen:
    """Start ``mlflow models serve`` on an internal port for one package.

    ``AQ_MODEL_VERSION`` tells the model which registry version it is, so every
    prediction carries it (docs/LLD.md section 4). One worker is enough for this
    load and keeps memory low.
    """
    env = {**os.environ, "AQ_MODEL_VERSION": str(version)}
    cmd = [
        sys.executable, "-m", "mlflow", "models", "serve",
        "-m", str(model_dir), "-h", "127.0.0.1", "-p", str(port),
        "--env-manager", "local", "--workers", "1",
    ]  # fmt: skip
    log.info("Starting %s", " ".join(cmd))
    return subprocess.Popen(cmd, env=env)


def wait_ready(proc: subprocess.Popen, port: int, timeout_s: float) -> None:
    """Wait until ``/ping`` answers 200, or raise ``ModelServerError``."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise ModelServerError(f"mlflow exited with code {proc.returncode}")
        try:
            if requests.get(f"http://127.0.0.1:{port}/ping", timeout=2).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise ModelServerError(f"mlflow not ready after {timeout_s:.0f} s")


def stop(proc: subprocess.Popen | None) -> None:
    """Stop an MLflow process (terminate, then kill after 10 s)."""
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


class ModelSupervisor:
    """Keep the proxy pointed at the MLflow process for the current champion."""

    def __init__(
        self,
        registry: ModelRegistryClient,
        upstream: Upstream,
        workdir: Path | None = None,
    ) -> None:
        """Set up with a registry, the proxy's upstream and a download folder."""
        self.registry = registry
        self.upstream = upstream
        self.workdir = workdir or Path(tempfile.mkdtemp(prefix="aq-model-"))
        self.version: str | None = None
        self.proc: subprocess.Popen | None = None
        self.port = PORTS[1]  # the first load flips to PORTS[0]

    def sync(self) -> bool:
        """Load the champion if it changed. Return True if the model changed.

        Never raises for a failed load: the old model keeps serving.
        """
        wanted = self.registry.champion_version()
        if wanted is None:
            log.warning("No champion in the registry yet; nothing to serve")
            return False
        if wanted == self.version:
            return False
        new_port = PORTS[0] if self.port == PORTS[1] else PORTS[1]
        proc = None
        try:
            package = download_package(self.registry, wanted, self.workdir)
            proc = start_mlflow(package, new_port, wanted)
            wait_ready(proc, new_port, START_TIMEOUT_S)
        except Exception as exc:  # keep serving the old model, whatever went wrong
            log.error("Could not load champion v%s: %s", wanted, exc)
            stop(proc)
            return False
        old = self.proc
        self.upstream.switch(f"http://127.0.0.1:{new_port}", wanted)
        stop(old)
        self.proc, self.port, self.version = proc, new_port, wanted
        log.info("Serving champion v%s", wanted)
        return True

    def watch(self, poll_s: float) -> None:
        """Poll forever; ``sync`` handles its own errors."""
        while True:
            try:
                self.sync()
            except Exception:  # the registry itself may be briefly unreachable
                log.exception("Registry check failed")
            time.sleep(poll_s)
