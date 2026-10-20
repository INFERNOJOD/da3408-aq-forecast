"""Load project settings from params.yaml and the environment."""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.common.errors import ConfigError
from src.common.logging_setup import get_logger

log = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PARAMS = PROJECT_ROOT / "params.yaml"


def load_params(path: str | Path = DEFAULT_PARAMS) -> dict[str, Any]:
    """Read params.yaml and return it as a dict.

    Raises ConfigError if the file is missing, is not valid YAML, or is not
    a mapping at the top level.
    """
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"Params file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Params file is not valid YAML: {path}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Params file must contain a mapping: {path}")
    log.debug("Loaded params from %s", path)
    return data


def load_env(path: str | Path | None = None) -> None:
    """Load a .env file into the environment, if one exists.

    Real environment variables always win over values in the file.
    """
    env_path = Path(path) if path else PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
        log.debug("Loaded env file %s", env_path)


def require_env(name: str) -> str:
    """Return an environment variable or raise ConfigError if unset/empty."""
    value = os.environ.get(name, "")
    if not value:
        raise ConfigError(f"Required environment variable not set: {name}")
    return value
