"""The Forecaster: turns a city and the replay clock into a forecast response."""

import pandas as pd

from src.backend import aqi
from src.backend.errors import ApiError
from src.backend.model_client import ModelServerClient, ModelUnavailableError
from src.backend.registry_view import RegistryView
from src.backend.replay import ReplayClock
from src.backend.store import ServingStore
from src.common.logging_setup import get_logger
from src.common.schema import HORIZONS

log = get_logger(__name__)


class Forecaster:
    """Builds the model input for one city and formats the answer."""

    def __init__(
        self,
        store: ServingStore,
        client: ModelServerClient,
        registry: RegistryView,
        clock: ReplayClock,
    ) -> None:
        """Keep the collaborators; nothing is loaded here."""
        self.store, self.client = store, client
        self.registry, self.clock = registry, clock

    def forecast(self, city: str, city_code: int) -> dict:
        """Return the GET /forecast body for ``city`` at the current sim time.

        Raises ApiError 503 NO_DATA if the store has no row for that hour, and
        ModelUnavailableError if the model server cannot answer.
        """
        issued = pd.Timestamp(self.clock.sim_time)
        row = self.store.row(city, issued)
        if row is None:
            raise ApiError(503, "NO_DATA", f"No data for {city} at {issued}.")
        rows = [{**row, "horizon_h": h} for h in HORIZONS]
        preds = self.client.predict(rows)
        versions = {str(p.get("model_version")) for p in preds}
        if len(versions) != 1:
            raise ModelUnavailableError("Model server mixed versions in one answer")
        version = versions.pop()
        forecasts = []
        for horizon, pred in zip(HORIZONS, preds, strict=True):
            pm25 = round(max(float(pred["pm25"]), 0.0), 1)
            forecasts.append(
                {
                    "horizon_h": horizon,
                    "valid_at": (issued + pd.Timedelta(hours=horizon)).isoformat(),
                    "pm25": pm25,
                    **aqi.categorize(pm25),
                }
            )
        observed = row["pm25"]
        return {
            "city": city,
            "issued_at": issued.isoformat(),
            "latest_observed_pm25": None if observed is None else round(observed, 1),
            "forecasts": forecasts,
            "model": self.registry.info(None if version == "unversioned" else version),
        }
