"""Prometheus metrics of the backend (docs/LLD.md section 5).

Each app gets its own registry, so tests can create several apps in one process.
"""

import math

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ProcessCollector,
)

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)


class Metrics:
    """The backend's collectors, created on one registry."""

    def __init__(self) -> None:
        """Create every metric listed for the backend in the LLD."""
        self.registry = CollectorRegistry()
        r = self.registry
        # Memory and CPU of this process (process_resident_memory_bytes, ...).
        # The default registry has them; a private registry needs them added.
        ProcessCollector(registry=r)
        self.requests = Counter(
            "aq_http_requests_total",
            "HTTP requests.",
            ["method", "path", "status"],
            registry=r,
        )
        self.duration = Histogram(
            "aq_http_request_duration_seconds",
            "HTTP request time.",
            ["method", "path"],
            buckets=LATENCY_BUCKETS,
            registry=r,
        )
        self.forecast = Gauge(
            "aq_forecast_pm25",
            "Last forecast PM2.5.",
            ["city", "horizon_h"],
            registry=r,
        )
        self.drift_psi = Gauge("aq_drift_psi", "PSI per city.", ["city"], registry=r)
        self.drift_threshold = Gauge(
            "aq_drift_threshold", "PSI threshold per city.", ["city"], registry=r
        )
        self.cities_exceeding = Gauge(
            "aq_drift_cities_exceeding", "Cities above their threshold.", registry=r
        )
        self.mae_ratio = Gauge(
            "aq_rolling_mae_ratio", "Rolling MAE ratio.", ["city"], registry=r
        )
        self.mae_ratio_pooled = Gauge(
            "aq_rolling_mae_ratio_pooled", "Pooled rolling MAE ratio.", registry=r
        )
        self.drift_detected = Gauge(
            "aq_drift_detected", "1 when the any_drift rule is true.", registry=r
        )
        self.model_version = Gauge("aq_model_version", "Champion version.", registry=r)
        self.sim_time = Gauge(
            "aq_replay_sim_time_seconds", "Replay clock (epoch).", registry=r
        )
        self.retrain_requests = Counter(
            "aq_retrain_requests_total", "Retrain requests.", ["reason"], registry=r
        )
        self.model_errors = Counter(
            "aq_model_server_errors_total", "Model server failures.", registry=r
        )

    def set_drift(self, report: dict) -> None:
        """Copy a drift report into the gauges.

        An unknown (None) value clears its series instead of being skipped.
        Skipping it kept the last replay value after a replay reset, when the
        windows are empty again: the pooled MAE ratio stayed at 1.70 and
        ``ForecastErrorHigh`` kept firing (docs/metrics.md, 2026-11-10).
        """
        for row in report["cities"]:
            city = row["city"]
            _set_or_clear(self.drift_psi, city, row["psi"])
            _set_or_clear(self.drift_threshold, city, row["psi_threshold"])
            _set_or_clear(self.mae_ratio, city, row["mae_ratio_1h"])
        self.cities_exceeding.set(report["cities_exceeding"])
        pooled = report["mae_ratio_pooled"]
        # An unlabelled gauge cannot be removed, so "no value" is NaN. In
        # Prometheus NaN > 1.5 is false, so the alert does not fire on it.
        self.mae_ratio_pooled.set(math.nan if pooled is None else pooled)
        self.drift_detected.set(1 if report["any_drift"] else 0)


def _set_or_clear(gauge: Gauge, city: str, value: float | None) -> None:
    """Set the city's series, or remove it when the value is unknown."""
    if value is not None:
        gauge.labels(city).set(value)
        return
    try:
        gauge.remove(city)
    except KeyError:  # the series did not exist yet
        pass
