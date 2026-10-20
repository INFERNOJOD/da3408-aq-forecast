"""Move the ``champion`` alias back to the previous version, or to a named one.

Usage:
    python -m scripts.rollback            # champion <- previous
    python -m scripts.rollback --version 2
    python -m scripts.rollback --list     # show versions and aliases

The model server picks up the change within 30 seconds (docs/HLD.md).
"""

import argparse
import sys

from src.common.config import load_env, load_params
from src.common.errors import RegistryError
from src.common.logging_setup import configure_logging, get_logger
from src.pipeline.registry import ModelRegistryClient

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Run the rollback (or the listing). Returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", help="version to roll back to (default: previous)")
    parser.add_argument("--list", action="store_true", help="list versions and exit")
    args = parser.parse_args(argv)
    configure_logging()
    load_env()
    registry = ModelRegistryClient(load_params()["promotion"]["model_name"])
    if args.list:
        for row in registry.versions():
            print(row["version"], ",".join(row["aliases"]) or "-", row["mlflow_run_id"])
        return 0
    try:
        old, new = registry.rollback(args.version)
    except RegistryError as exc:
        log.error("Rollback failed: %s", exc)
        return 1
    print(f"champion: {old} -> {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
