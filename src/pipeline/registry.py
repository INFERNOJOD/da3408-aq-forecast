"""The model registry, seen through the two aliases the project uses.

``champion`` is the version that is served. ``previous`` is the version that was
champion before the last promotion. Both are MLflow registry aliases, so moving
them is a metadata change: instant, recorded by MLflow, and reversible. Promotion
and rollback use the same move (see docs/HLD.md, "Registry and rollback").
"""

import os

import mlflow
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from src.common.errors import RegistryError
from src.common.logging_setup import get_logger

log = get_logger(__name__)

CHAMPION = "champion"
PREVIOUS = "previous"
DEFAULT_TRACKING_URI = "sqlite:///mlflow.db"


def tracking_uri() -> str:
    """Return the MLflow tracking and registry URI (env var, else local database)."""
    return os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)


class ModelRegistryClient:
    """Registry operations for one registered model name."""

    def __init__(self, name: str, uri: str | None = None) -> None:
        """Connect to the registry at ``uri`` (default: ``tracking_uri()``)."""
        self.name = name
        self.uri = uri or tracking_uri()
        mlflow.set_tracking_uri(self.uri)
        self.client = MlflowClient(tracking_uri=self.uri, registry_uri=self.uri)

    def _alias_version(self, alias: str) -> str | None:
        """Version number the alias points to, or None if it is not set."""
        try:
            return str(self.client.get_model_version_by_alias(self.name, alias).version)
        except MlflowException:
            return None

    def champion_version(self) -> str | None:
        """Version that is champion, or None before the first promotion."""
        return self._alias_version(CHAMPION)

    def previous_version(self) -> str | None:
        """Version that was champion before the last promotion, if any."""
        return self._alias_version(PREVIOUS)

    def champion_uri(self) -> str | None:
        """Model URI of the champion, or None when there is no champion."""
        return f"models:/{self.name}@{CHAMPION}" if self.champion_version() else None

    def versions(self) -> list[dict]:
        """All versions, newest first, with their aliases and tags."""
        found = self.client.search_model_versions(f"name='{self.name}'")
        aliases: dict[str, list[str]] = {}
        for alias in (CHAMPION, PREVIOUS):
            version = self._alias_version(alias)
            if version:
                aliases.setdefault(version, []).append(alias)
        rows = [
            {
                "version": str(v.version),
                "aliases": aliases.get(str(v.version), []),
                "mlflow_run_id": v.run_id,
                "created_ms": v.creation_timestamp,
                "tags": dict(v.tags),
            }
            for v in found
        ]
        return sorted(rows, key=lambda r: int(r["version"]), reverse=True)

    def _move_champion(self, version: str) -> None:
        """Point champion at ``version`` and previous at the old champion."""
        old = self.champion_version()
        if old == version:
            raise RegistryError(f"Version {version} is already the champion")
        if old is not None:
            self.client.set_registered_model_alias(self.name, PREVIOUS, old)
        self.client.set_registered_model_alias(self.name, CHAMPION, version)
        log.info("Champion %s -> %s (previous = %s)", old, version, old)

    def promote(self, model_uri: str, run_id: str, tags: dict[str, str]) -> str:
        """Register a new version from ``model_uri`` and make it champion.

        Returns the new version number. The old champion becomes ``previous``.
        """
        try:
            try:
                self.client.get_registered_model(self.name)
            except MlflowException:  # first promotion ever: create the entry
                self.client.create_registered_model(self.name)
            created = self.client.create_model_version(
                self.name, model_uri, run_id=run_id, tags=tags
            )
        except MlflowException as exc:
            raise RegistryError(f"Cannot register {model_uri}: {exc}") from exc
        version = str(created.version)
        self._move_champion(version)
        return version

    def rollback(self, version: str | None = None) -> tuple[str | None, str]:
        """Make ``version`` (default: the ``previous`` alias) the champion.

        Returns (from_version, to_version). The version that was champion
        becomes ``previous``, so a rollback can be rolled back.
        """
        target = version if version is not None else self.previous_version()
        if target is None:
            raise RegistryError("No previous version to roll back to")
        target = str(target)
        try:
            self.client.get_model_version(self.name, target)
        except MlflowException as exc:
            raise RegistryError(f"Version {target} does not exist") from exc
        old = self.champion_version()
        self._move_champion(target)
        return old, target
