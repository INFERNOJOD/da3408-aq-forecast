"""Prometheus metrics of the backend (docs/LLD.md section 5).

Each app gets its own registry, so tests can create several apps in one process.
"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)


class Metrics:
    """The backend's collectors, created on one registry."""

    def __init__(self) -> None:
        """Create every metric listed for the backend in the LLD."""
        self.registry = CollectorRegistry()
        r = self.registry
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
        """Copy a drift report into the gauges. Unknown (None) values are skipped."""
        for row in report["cities"]:
            if row["psi"] is not None:
                self.drift_psi.labels(row["city"]).set(row["psi"])
            if row["psi_threshold"] is not None:
                self.drift_threshold.labels(row["city"]).set(row["psi_threshold"])
            if row["mae_ratio_1h"] is not None:
                self.mae_ratio.labels(row["city"]).set(row["mae_ratio_1h"])
        self.cities_exceeding.set(report["cities_exceeding"])
        if report["mae_ratio_pooled"] is not None:
            self.mae_ratio_pooled.set(report["mae_ratio_pooled"])
        self.drift_detected.set(1 if report["any_drift"] else 0)
