"""Read-only access to the stored features of the replay period."""

from pathlib import Path

import pandas as pd

from src.common.errors import ConfigError
from src.common.logging_setup import get_logger
from src.common.schema import FEATURE_COLUMNS

log = get_logger(__name__)


class ServingStore:
    """Feature rows from ``serving.parquet``, indexed by (city, hour)."""

    def __init__(self, path: Path) -> None:
        """Load the file once (about 30,000 rows, a few MB)."""
        if not Path(path).exists():
            raise ConfigError(f"Serving features not found: {path} (run dvc repro)")
        frame = pd.read_parquet(path)
        frame["Datetime"] = pd.to_datetime(frame["Datetime"])
        self._frame = frame.set_index(["City", "Datetime"]).sort_index()
        log.info("Loaded %d serving rows from %s", len(frame), path)

    def row(self, city: str, hour: pd.Timestamp) -> dict | None:
        """Feature columns and ``pm25`` for one city-hour, or None if absent.

        Missing numbers come back as None, so they become JSON null.
        """
        try:
            found = self._frame.loc[(city, hour)]
        except KeyError:
            return None
        wanted = [*FEATURE_COLUMNS, "pm25"]
        return {k: (None if pd.isna(found[k]) else found[k].item()) for k in wanted}

    def window(self, city: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """All stored columns of ``city`` for every hour from ``start`` to ``end``.

        The result has one row per hour (both ends included); hours that are
        not stored come back as rows of NaN, so a window always has its full
        length.
        """
        hours = pd.date_range(start, end, freq="h")
        try:
            rows = self._frame.loc[city]
        except KeyError:
            return pd.DataFrame(index=hours, columns=self._frame.columns)
        return rows.reindex(hours)
