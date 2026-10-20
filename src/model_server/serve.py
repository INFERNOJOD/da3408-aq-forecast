"""Entry point of the model-server container: ``python -m src.model_server.serve``.

Environment: ``MLFLOW_TRACKING_URI`` (registry), ``MODEL_NAME`` (default
aq-pm25), ``MODEL_PORT`` (5001), ``METRICS_PORT`` (8001), ``POLL_SECONDS`` (30).
"""

import os

from src.common.config import load_env
from src.common.logging_setup import configure_logging, get_logger
from src.model_server.proxy import Upstream, start_proxy
from src.model_server.supervisor import ModelSupervisor
from src.pipeline.registry import ModelRegistryClient

log = get_logger(__name__)


def main() -> None:
    """Start the proxy, load the champion and keep following the alias."""
    load_env()
    configure_logging()
    registry = ModelRegistryClient(os.environ.get("MODEL_NAME", "aq-pm25"))
    upstream = Upstream()
    start_proxy(
        upstream,
        int(os.environ.get("MODEL_PORT", "5001")),
        int(os.environ.get("METRICS_PORT", "8001")),
    )
    ModelSupervisor(registry, upstream).watch(
        float(os.environ.get("POLL_SECONDS", "30"))
    )


if __name__ == "__main__":
    main()
