"""Find out which code and data version a run used.

Used by the training stage to tag every MLflow run, so a result can be traced
back to a git commit and a data version (see docs/HLD.md, "Reproducibility").
"""

import hashlib
import subprocess
from pathlib import Path

import pandas as pd
import yaml

from src.common.errors import ConfigError
from src.common.logging_setup import get_logger

log = get_logger(__name__)


def _git(*args: str) -> str | None:
    """Run a git command and return its output, or None if git fails."""
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, timeout=20
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        log.warning("git %s failed", " ".join(args))
        return None


def git_commit() -> str:
    """Return the full hash of the current commit, or 'unknown'."""
    return _git("rev-parse", "HEAD") or "unknown"


def git_dirty() -> bool:
    """Return True if tracked files have uncommitted changes.

    The commit hash only describes the code exactly when this is False.
    Untracked files are ignored: generated data and caches are untracked.
    """
    status = _git("status", "--porcelain", "--untracked-files=no")
    return bool(status)


def dvc_raw_md5(dvc_file: str | Path = "data/raw.dvc") -> str:
    """Return the DVC hash of the raw data (the data version).

    Raises ConfigError if the .dvc file is missing or has no hash.
    """
    path = Path(dvc_file)
    try:
        meta = yaml.safe_load(path.read_text(encoding="utf-8"))
        return str(meta["outs"][0]["md5"])
    except FileNotFoundError as exc:
        raise ConfigError(f"DVC file not found: {path}") from exc
    except (KeyError, IndexError, TypeError, yaml.YAMLError) as exc:
        raise ConfigError(f"No data hash in {path}") from exc


def parquet_data_md5(
    path: str | Path, sort_by: tuple[str, ...] = ("City", "Datetime")
) -> str:
    """Hash the values in a Parquet dataset, whatever the file layout.

    Used as the version of the feature files, which DVC only hashes after the
    stage has finished. Hashing the raw bytes does not work: Spark names every
    part file with a random id, and I found that even the bytes inside a file can
    differ between two runs on identical data. So the rows are sorted by
    ``sort_by`` and hashed value by value, with the column names.
    """
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Path not found: {path}")
    df = pd.read_parquet(path)
    missing = [c for c in sort_by if c not in df.columns]
    if missing:
        raise ConfigError(f"Cannot sort {path} by missing columns {missing}")
    df = df.sort_values(list(sort_by)).reset_index(drop=True)
    row_hashes = pd.util.hash_pandas_object(df, index=False).to_numpy()
    digest = hashlib.md5()  # noqa: S324 - a version fingerprint, not security
    digest.update(",".join(map(str, df.columns)).encode())
    digest.update(row_hashes.tobytes())
    return digest.hexdigest()
