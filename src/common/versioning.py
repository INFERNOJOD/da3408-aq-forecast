"""Find out which code and data version a run used.

Used by the training stage to tag every MLflow run, so a result can be traced
back to a git commit and a data version (see docs/HLD.md, "Reproducibility").
"""

import hashlib
import subprocess
from pathlib import Path

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


def dir_md5(path: str | Path) -> str:
    """Hash all files under a directory (names and contents) into one md5.

    Used as the version of the feature files, which DVC only hashes after the
    stage has finished.
    """
    root = Path(path)
    if not root.exists():
        raise ConfigError(f"Path not found: {root}")
    files = (
        [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    )
    digest = hashlib.md5()  # noqa: S324 - a version fingerprint, not security
    for file in files:
        if file.name.startswith(".") or file.name.endswith(".crc"):
            continue  # Spark checksum files are not part of the data
        digest.update(str(file.relative_to(root.parent)).encode())
        with file.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    return digest.hexdigest()
