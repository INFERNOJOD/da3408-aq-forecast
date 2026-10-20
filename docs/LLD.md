# Low-Level Design

This document is the interface contract. Code must match it exactly; any endpoint change updates this file in the same commit.

## 1. Conventions

- Backend base URL: `https://<host>:8000` (`BACKEND_URL` in the frontend). JSON only, UTF-8.
- Times are ISO 8601 without a timezone, in IST, as in the source data (e.g. `2020-03-25T14:00:00`).
- `sim_time` is the replay clock's current hour. Forecasts are issued "as of" `sim_time`.
- `city` must be one of: `Delhi, Chennai, Lucknow, Hyderabad, Bengaluru, Jaipur, Kolkata` (case-sensitive).
- Ops auth: header `Authorization: Bearer <OPS_API_KEY>`. A missing or wrong key returns `401`.
- Error body for **every** non-2xx response, including validation errors (FastAPI's default 422 body is overridden):

```json
{"error": {"code": "UNKNOWN_CITY", "message": "City 'Pune' is not supported."}}
```

| HTTP | code | When |
|------|------|------|
| 400 | `BAD_REQUEST` | Semantically invalid request (e.g. rollback to a non-existent version) |
| 401 | `UNAUTHORIZED` | Missing or wrong API key on `/ops/*` |
| 404 | `UNKNOWN_CITY` | City not in the supported list |
| 409 | `CONFLICT` | Retrain already pending or running; replay already in the requested state |
| 422 | `VALIDATION_ERROR` | Wrong type, missing field, value out of range |
| 503 | `MODEL_UNAVAILABLE` | Model server unreachable or returned an error |
| 503 | `NO_DATA` | No feature row for the city at `sim_time` (data gap) |
| 500 | `INTERNAL_ERROR` | Unexpected; logged with a traceback, generic message returned |

## 2. Public endpoints (no auth)

### GET `/health`
200:
```json
{"status": "ok", "model_server": "up", "model_version": "3", "sim_time": "2020-03-25T14:00:00", "replay_running": true}
```
`status` is `"degraded"` when `model_server` is `"down"`. The endpoint still returns 200, so it works as a liveness probe.

### GET `/cities`
200:
```json
{"cities": ["Delhi", "Chennai", "Lucknow", "Hyderabad", "Bengaluru", "Jaipur", "Kolkata"]}
```

### GET `/aqi/categories`
200: the CPCB table from `HLD.md` §4.
```json
{"categories": [{"name": "Good", "min": 0, "max": 30, "color": "#00B050", "advice": "Minimal impact."}, "..."],
 "note": "Indicative: official AQI uses 24-hour averages."}
```
The `max` of the last category (`Severe`) is `null`.

### GET `/forecast?city=<city>`
| Param | Type | Required | Rule |
|-------|------|----------|------|
| `city` | string | yes | one of the supported cities |

200:
```json
{
  "city": "Delhi",
  "issued_at": "2020-03-25T14:00:00",
  "latest_observed_pm25": 52.3,
  "forecasts": [
    {"horizon_h": 1,  "valid_at": "2020-03-25T15:00:00", "pm25": 49.8,
     "aqi_category": "Satisfactory", "aqi_color": "#92D050", "advice": "Minor breathing discomfort to sensitive people."},
    {"horizon_h": 24, "valid_at": "2020-03-26T14:00:00", "pm25": 44.1,
     "aqi_category": "Satisfactory", "aqi_color": "#92D050", "advice": "Minor breathing discomfort to sensitive people."}
  ],
  "model": {"name": "aq-pm25", "version": "3", "mlflow_run_id": "8f1c...", "git_commit": "6b50365"}
}
```
`pm25` is in µg/m³, rounded to 1 decimal and clipped at 0. `latest_observed_pm25` may be `null` if the current hour is missing.
Errors: 404 `UNKNOWN_CITY`, 422, 503 `MODEL_UNAVAILABLE` / `NO_DATA`.

### GET `/pipeline/stages`
The DVC DAG with the status of each stage in the most recent run.
```json
{"run_id": "20201020-101500", "stages": [
  {"name": "ingest", "deps": [], "status": "success", "duration_s": 41.2, "rows_out": 3296958, "rows_per_sec": 80023},
  {"name": "validate", "deps": ["ingest"], "status": "success", "duration_s": 12.0, "rows_out": 3296958, "rows_per_sec": 274746},
  "..."
]}
```
`status` ∈ `success | failed | running | skipped | not_run`. Stages, in order: `ingest, validate, features, train, evaluate, test, register`.

### GET `/pipeline/runs?limit=<n>`
`limit`: int, 1-100, default 20. The newest run comes first.
```json
{"runs": [
  {"run_id": "20201020-101500", "trigger": "drift_alert", "status": "failed", "started_at": "2026-10-20T10:15:00",
   "duration_s": 212.4, "cutoff": "2020-04-02T23:00:00", "failed_stage": "validate",
   "error": "PM2.5 > 1000 in 12 rows", "git_commit": "abc1234", "mlflow_run_id": null, "promoted": false}
]}
```
`trigger` ∈ `manual | drift_alert | initial`. `started_at` is wall-clock time (not simulated).

### GET `/pipeline/models`
Registry versions of `aq-pm25`, newest first.
```json
{"models": [
  {"version": "3", "aliases": ["champion"], "mlflow_run_id": "8f1c...", "created_at": "2026-10-20T10:19:00",
   "cutoff": "2020-04-02T23:00:00", "mae_1h": 6.2, "mae_24h": 14.9, "git_commit": "abc1234"}
]}
```

### GET `/metrics`
Prometheus text format (see §5).

## 3. Ops endpoints (Bearer API key)

### GET `/ops/drift`
```json
{"sim_time": "2020-04-01T09:00:00", "window_h": 168, "psi_threshold": 0.2, "mae_ratio_threshold": 1.5,
 "cities": [{"city": "Delhi", "psi": 0.41, "mae_ratio_1h": 1.8, "drifted": true}, "..."],
 "any_drift": true}
```
`psi` and `mae_ratio_1h` are `null` until 24 replayed hours exist for that city.

### GET `/ops/replay`  ·  POST `/ops/replay`
Request (POST):
```json
{"action": "start", "speed_hps": 1.0}
```
`action` ∈ `start | stop | reset`. `speed_hps`: float, 0.1-20, optional (default `REPLAY_SPEED_HPS`). `reset` sets the clock back to `2020-03-25T00:00:00` and clears the drift windows.

Response (both methods), 200:
```json
{"running": true, "sim_time": "2020-03-25T00:00:00", "speed_hps": 1.0, "start": "2020-03-25T00:00:00", "end": "2020-06-30T23:00:00"}
```
409 if `start` is sent while already running, or `stop` while stopped. The replay stops automatically at `end`.

### POST `/ops/retrain`
Request:
```json
{"reason": "manual"}
```
`reason`: string, 1-200 chars. The cutoff is set to the current `sim_time`.

202:
```json
{"request_id": "rt-20201020-101500", "cutoff": "2020-04-02T23:00:00", "status": "queued"}
```
409 if a request is already queued or running. The backend writes `ops/requests/<request_id>.json` (schema in §6), which the ops runner consumes.

### POST `/ops/rollback`
Request:
```json
{"version": "2"}
```
`version` is optional; if omitted, the `previous` alias is used.

200:
```json
{"from_version": "3", "to_version": "2"}
```
400 if the version does not exist or is already champion. The model server picks up the change within 30 s.

### POST `/ops/alerts`
The Alertmanager webhook (payload format v4, unchanged). For each alert with `status=firing` and `labels.action="retrain"`,
the backend creates a retrain request with reason `drift_alert:<alertname>`, unless one was created in the last
`RETRAIN_COOLDOWN_MIN` (30) minutes. All alerts are logged.
200: `{"received": 2, "retrain_requested": true}`

## 4. Model server contract (backend → MLflow)

`POST {MODEL_SERVER_URL}/invocations` with the MLflow `dataframe_split` format. One row per (city, horizon).

| Column | Type | Notes |
|--------|------|-------|
| `horizon_h` | int | 1 or 24 |
| `city_code` | int | index in the city list (0-6), a categorical feature in LightGBM |
| `hour`, `dow`, `month` | int | calendar features of `issued_at` |
| `is_weekend` | int | 0/1 |
| `pm25_lag_1`, `pm25_lag_2`, `pm25_lag_3`, `pm25_lag_24`, `pm25_lag_168` | float or null | lag k = value at t−k+1 (lag_1 = current hour) |
| `pm25_roll_mean_6`, `pm25_roll_mean_24`, `pm25_roll_std_24` | float or null | over hours t−5..t / t−23..t |
| `pm10_lag_1`, `no2_lag_1`, `co_lag_1`, `so2_lag_1`, `o3_lag_1` | float or null | current hour co-pollutants |

The canonical list lives in `src/common/schema.py::FEATURES`. A test asserts that it equals this table.

Response:
```json
{"predictions": [{"pm25": 49.8, "model_version": "3"}, {"pm25": 44.1, "model_version": "3"}]}
```
`GET /ping` returns 200 when the model is loaded.

## 5. Prometheus metrics

| Component | Metric | Type | Labels |
|-----------|--------|------|--------|
| backend | `aq_http_requests_total` | counter | `method, path, status` |
| backend | `aq_http_request_duration_seconds` | histogram | `method, path` |
| backend | `aq_forecast_pm25` | gauge | `city, horizon_h` |
| backend | `aq_drift_psi` | gauge | `city` |
| backend | `aq_rolling_mae_ratio` | gauge | `city` |
| backend | `aq_model_version` | gauge (value = version) | — |
| backend | `aq_replay_sim_time_seconds` | gauge (epoch) | — |
| backend | `aq_retrain_requests_total` | counter | `reason` |
| backend | `aq_model_server_errors_total` | counter | — |
| model server (`:8001`) | `aq_model_predictions_total` | counter | `horizon_h` |
| model server | `aq_model_predict_duration_seconds` | histogram | — |
| model server | `aq_model_loaded_version` | gauge | — |
| frontend (`:8502`) | `aq_ui_page_views_total` | counter | `page` |
| frontend | `aq_ui_backend_call_duration_seconds` | histogram | `endpoint` |
| frontend | `aq_ui_backend_errors_total` | counter | `endpoint` |
| pipeline (Pushgateway, job `aq_pipeline`) | `aq_stage_duration_seconds` | gauge | `stage, run_id` |
| pipeline | `aq_stage_rows_per_second` | gauge | `stage` |
| pipeline | `aq_stage_status` | gauge (1 = success, 0 = failed) | `stage` |
| pipeline | `aq_pipeline_last_success_timestamp` | gauge | — |
| host | node-exporter defaults | — | — |

Alert rules (`monitoring/alerts.yml`):

| Alert | Expression (summary) | for | labels |
|-------|----------------------|-----|--------|
| `PM25DriftHigh` | `max(aq_drift_psi) > 0.2` | 1m | `action=retrain` |
| `ForecastErrorHigh` | `max(aq_rolling_mae_ratio) > 1.5` | 1m | `action=retrain` |
| `BackendErrorRateHigh` | 5xx share of `aq_http_requests_total` > 5% over 5m | 2m | — |
| `TargetDown` | `up == 0` | 1m | — |
| `PipelineStageFailed` | `aq_stage_status == 0` | 0m | — |

## 6. Files and shared volumes

| Path | Writer | Reader | Content |
|------|--------|--------|---------|
| `data/interim/*.parquet` | ingest | validate, features | Typed copies of the raw CSVs |
| `data/features/train.parquet` | features | train, evaluate | Rows before the cutoff, with features and targets `y_1h`, `y_24h` |
| `data/features/serving.parquet` | features | backend (ro) | All hours 2020-01-01..2020-06-30 for the 7 cities. Features are causal (past only) and `pm25` actuals are included for replay scoring. |
| `reports/validation.json` | validate | console, docs | Check results |
| `reports/runs.jsonl` | every stage (via `stage_runner`) | backend `/pipeline/*` | One JSON line per stage execution: `{run_id, trigger, stage, status, started_at, duration_s, rows_in, rows_out, rows_per_sec, error, git_commit, cutoff}` |
| `ops/requests/<id>.json` | backend | ops runner | `{request_id, reason, cutoff, created_at, status}`. The runner updates `status` (`queued → running → done / failed / rolled_back`). |
| MLflow artifacts per run | train | backend, model server | `model/` (pyfunc), `drift_baseline.json`, `per_city_mae.csv`, `feature_importance.png`, `residuals.png` |

## 7. Pipeline stage contracts (`dvc.yaml`)

| Stage | Command | deps | outs / metrics |
|-------|---------|------|----------------|
| ingest | `python -m src.pipeline.ingest` | `data/raw`, `src/pipeline/ingest.py` | `data/interim/` |
| validate | `python -m src.pipeline.validate` | `data/interim/` | `reports/validation.json` (metric) |
| features | `python -m src.pipeline.features` | `data/interim/`, params `cities, cutoff, features` | `data/features/` |
| train | `python -m src.pipeline.train` | `data/features/train.parquet`, params `train, cutoff` | `models/candidate/`, `reports/train_metrics.json` |
| evaluate | `python -m src.pipeline.evaluate` | `models/candidate/`, `data/features/train.parquet` | `reports/eval.json` (candidate vs champion) |
| test | `python -m src.pipeline.test_gate` | `reports/eval.json` | `reports/gate.json` (`{"passed": bool, "reasons": [...]}`) |
| register | `python -m src.pipeline.register` | `reports/gate.json`, `models/candidate/` | `reports/register.json` (version, promoted) |

## 8. Environment variables

| Variable | Used by | Default |
|----------|---------|---------|
| `BACKEND_URL` | frontend | `https://backend:8000` |
| `OPS_API_KEY` | backend, frontend (console), alertmanager | — (required, in `.env`) |
| `MODEL_SERVER_URL` | backend | `http://model-server:5001` |
| `MLFLOW_TRACKING_URI` | backend, pipeline, model server | `http://mlflow:5000` |
| `REPLAY_SPEED_HPS` | backend | `1.0` |
| `RETRAIN_COOLDOWN_MIN` | backend | `30` |
| `TLS_CERT_FILE`, `TLS_KEY_FILE` | backend | `/certs/backend.crt`, `/certs/backend.key` |
| `PUSHGATEWAY_URL` | pipeline | `http://pushgateway:9091` |
