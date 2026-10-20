"""The FastAPI application. Routes follow docs/LLD.md section by section."""

import hmac
import time
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from src.backend import aqi, pipeline_view
from src.backend.drift import DriftReport
from src.backend.errors import ApiError, error_response, install_handlers
from src.backend.forecaster import Forecaster
from src.backend.metrics import Metrics
from src.backend.model_client import ModelServerClient, ModelUnavailableError
from src.backend.ops import RetrainQueue
from src.backend.registry_view import RegistryView
from src.backend.replay import MAX_SPEED, MIN_SPEED, ReplayClock
from src.backend.settings import Settings
from src.backend.store import ServingStore
from src.common.errors import RegistryError
from src.common.logging_setup import get_logger
from src.pipeline.registry import ModelRegistryClient

log = get_logger(__name__)


class ReplayRequest(BaseModel):
    """Body of POST /ops/replay."""

    action: Literal["start", "stop", "reset"]
    speed_hps: float | None = Field(default=None, ge=MIN_SPEED, le=MAX_SPEED)


class RetrainRequest(BaseModel):
    """Body of POST /ops/retrain."""

    reason: str = Field(min_length=1, max_length=200)


class RollbackRequest(BaseModel):
    """Body of POST /ops/rollback."""

    version: str | None = Field(default=None, min_length=1, max_length=20)


class AlertPayload(BaseModel):
    """The part of the Alertmanager webhook (v4) the backend reads."""

    model_config = {"extra": "allow"}
    alerts: list[dict] = Field(default_factory=list)


def create_app(
    settings: Settings,
    *,
    store: ServingStore | None = None,
    client: ModelServerClient | None = None,
    registry: RegistryView | None = None,
) -> FastAPI:
    """Build the app. Collaborators can be passed in, which is how tests run it."""
    if not settings.ops_api_key:
        raise ValueError("ops_api_key must not be empty")
    metrics = Metrics()
    clock = ReplayClock(
        datetime.fromisoformat(settings.replay_start),
        datetime.fromisoformat(settings.replay_end),
        settings.replay_speed_hps,
    )
    client = client or ModelServerClient(settings.model_server_url)
    registry = registry or RegistryView(ModelRegistryClient(settings.model_name))
    store = store or ServingStore(settings.serving_path)
    forecaster = Forecaster(store, client, registry, clock)
    queue = RetrainQueue(settings.ops_dir, settings.retrain_cooldown_min)
    drift = DriftReport(
        settings.cities,
        clock,
        settings.reports_dir,
        settings.drift_min_cities,
        settings.drift_mae_ratio,
        store,
        client,
        registry,
    )
    app = FastAPI(title="AQ forecast backend", version="1.0")
    install_handlers(app)

    @app.middleware("http")
    async def instrument(request: Request, call_next):
        """Count and time every request; turn crashes into the standard 500."""
        began = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 - last line of defence, logged below
            log.exception("Unhandled error on %s %s", request.method, request.url.path)
            response = error_response(500, "INTERNAL_ERROR", "Internal server error.")
        route = request.scope.get("route")
        path = route.path if route else "unmatched"
        metrics.requests.labels(request.method, path, str(response.status_code)).inc()
        metrics.duration.labels(request.method, path).observe(
            time.perf_counter() - began
        )
        return response

    def require_key(authorization: str | None = Header(default=None)) -> None:
        """Check ``Authorization: Bearer <key>`` in constant time."""
        scheme, _, token = (authorization or "").partition(" ")
        ok = scheme == "Bearer" and hmac.compare_digest(
            token.encode(), settings.ops_api_key.encode()
        )
        if not ok:
            raise ApiError(401, "UNAUTHORIZED", "Missing or wrong API key.")

    ops = [Depends(require_key)]

    # ---- public endpoints -------------------------------------------------

    @app.get("/health")
    def health() -> dict:
        up = client.is_up()
        return {
            "status": "ok" if up else "degraded",
            "model_server": "up" if up else "down",
            "model_version": registry.champion_version(),
            "sim_time": clock.state()["sim_time"],
            "replay_running": clock.running,
        }

    @app.get("/cities")
    def cities() -> dict:
        return {"cities": list(settings.cities)}

    @app.get("/aqi/categories")
    def aqi_categories() -> dict:
        return {"categories": aqi.categories(), "note": aqi.NOTE}

    @app.get("/forecast")
    def forecast(city: str) -> dict:
        if city not in settings.cities:
            raise ApiError(404, "UNKNOWN_CITY", f"City '{city}' is not supported.")
        try:
            body = forecaster.forecast(city, settings.cities.index(city))
        except ModelUnavailableError as exc:
            metrics.model_errors.inc()
            log.warning("Forecast failed: %s", exc)
            raise ApiError(
                503, "MODEL_UNAVAILABLE", "The model is unavailable."
            ) from exc
        for item in body["forecasts"]:
            metrics.forecast.labels(city, str(item["horizon_h"])).set(item["pm25"])
        return body

    @app.get("/pipeline/stages")
    def pipeline_stages() -> dict:
        return pipeline_view.stages(settings.reports_dir)

    @app.get("/pipeline/runs")
    def pipeline_runs(limit: int = Query(default=20, ge=1, le=100)) -> dict:
        return {"runs": pipeline_view.runs(settings.reports_dir, limit)}

    @app.get("/pipeline/models")
    def pipeline_models() -> dict:
        return {"models": registry.models()}

    @app.get("/metrics")
    def prometheus() -> Response:
        metrics.sim_time.set(clock.sim_time.timestamp())
        version = registry.champion_version()
        if version and version.isdigit():
            metrics.model_version.set(int(version))
        metrics.set_drift(drift.report())
        return Response(
            generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST
        )

    # ---- ops endpoints ----------------------------------------------------

    @app.get("/ops/drift", dependencies=ops)
    def ops_drift() -> dict:
        report = drift.report()
        metrics.set_drift(report)
        return report

    @app.get("/ops/replay", dependencies=ops)
    def replay_state() -> dict:
        return clock.state()

    @app.post("/ops/replay", dependencies=ops)
    def replay_apply(body: ReplayRequest) -> dict:
        return clock.apply(body.action, body.speed_hps)

    @app.post("/ops/retrain", status_code=202, dependencies=ops)
    def retrain(body: RetrainRequest) -> dict:
        record = queue.create(body.reason, clock.state()["sim_time"])
        metrics.retrain_requests.labels("manual").inc()
        return {
            "request_id": record["request_id"],
            "cutoff": record["cutoff"],
            "status": record["status"],
        }

    @app.post("/ops/rollback", dependencies=ops)
    def rollback(body: RollbackRequest) -> dict:
        try:
            old, new = registry.rollback(body.version)
        except RegistryError as exc:
            raise ApiError(400, "BAD_REQUEST", str(exc)) from exc
        log.warning("Rollback: champion %s -> %s", old, new)
        return {"from_version": old, "to_version": new}

    @app.post("/ops/alerts", dependencies=ops)
    def alerts(body: AlertPayload) -> dict:
        requested = queue.from_alerts(
            body.alerts, clock.state()["sim_time"], drift.summary
        )
        if requested:
            metrics.retrain_requests.labels("drift_alert").inc()
        return {"received": len(body.alerts), "retrain_requested": requested}

    return app
