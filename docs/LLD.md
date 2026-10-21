# Low-Level Design

This document is the interface contract. Code must match it exactly; any endpoint change updates this file in the same commit.

## 1. Conventions

- Backend base URL: `https://<host>:8000` (`BACKEND_URL` in the frontend). JSON only, UTF-8. The certificate is signed by the project's own CA (`certs/ca.crt`, made by `scripts/make_certs.sh`); clients check it against that file.
- Users open the frontend at `https://<host>/` (the TLS proxy, host port 443). `http://<host>/` and `http://<host>:8501/` answer `301` with a redirect to the same path on `https://<host>/`.
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
| 404 | `NOT_FOUND` | No such route |
| 405 | `METHOD_NOT_ALLOWED` | Route exists, method does not |
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
`status` is `"degraded"` when `model_server` is `"down"` (`GET /ping` failed). The endpoint still returns 200, so it works as a liveness probe. `model_version` is the registry's `champion` version (cached for 30 s), or `null` if the registry cannot be read.

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
`pm25` is in µg/m³, rounded to 1 decimal and clipped at 0. `latest_observed_pm25` may be `null` if the current hour is missing. `model.version` is the version the model server reported in its answer; `mlflow_run_id` and `git_commit` (7 characters) come from that version's registry entry and are `null` if the registry cannot be read. The category of a value is the one whose lowest value is not above it, so 30.5 is `Good` and 31 is `Satisfactory`.
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
`trigger` ∈ `manual | drift_alert | initial`. `started_at` is wall-clock time (not simulated). A run is all lines of `runs.jsonl` with the same `run_id`. Its `status` is `failed` if any stage failed and `success` otherwise (DVC skips unchanged stages, so a run does not always contain all seven, and the file cannot say that a run is still going). `promoted` and `mlflow_run_id` come from `reports/register.json`, so they are filled only for the newest run and only if it ran the `register` stage; otherwise they are `null`.

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
200 (example values):
```json
{"sim_time": "2020-04-01T00:00:00", "window_h": 168, "reference_block": 1,
 "min_cities": 4, "mae_ratio_threshold": 1.5,
 "cities": [{"city": "Delhi", "psi": 3.37, "psi_threshold": 2.0307, "exceeds": true, "votes": true, "mae_ratio_1h": 0.71},
            {"city": "Kolkata", "psi": 5.2, "psi_threshold": null, "exceeds": null, "votes": false, "mae_ratio_1h": 0.64}, "..."],
 "cities_exceeding": 4, "mae_ratio_pooled": 0.76,
 "psi_condition": true, "mae_condition": false, "any_drift": true}
```
`any_drift` is `psi_condition`: at least `min_cities` (default 4, `drift.min_cities` in `params.yaml`) voting cities have `exceeds` true. A city with `psi_threshold` null (fewer than three reference years, so no threshold could be computed; this is Kolkata) does not vote, and its `exceeds` is `null`.

`mae_condition` is true when `mae_ratio_pooled` is above `mae_ratio_threshold` (`drift.mae_ratio_warn`, 1.5). It is reported and drives the `ForecastErrorHigh` warning, but it is **not** part of `any_drift`. In Stage 11 I measured that the model's error during the lockdown is lower than in normal springs, so this condition never held on the lockdown and the old two-condition rule could not fire (`docs/metrics.md`, Stage 11).

`psi` compares the last 168 replayed hours of `pm25_lag_1` with the same-season reference block `reference_block` = `min(h // 168, 13)` in `reports/baseline_stats.json`, where `h` is the replay hour of the window's last hour. Bins with no values count as a share of 0.0001 on both sides, so the PSI stays finite. `exceeds` is `psi > psi_threshold`, with the per-city threshold from `reports/drift_thresholds.json`. `psi` and `exceeds` are `null` until 168 replayed hours exist, or when fewer than 84 of the 168 values are present.

`mae_ratio_1h` is the city's 1 h MAE over the forecasts issued in the last 72 replayed hours whose actual value is already known, divided by the champion's 1 h MAE on its evaluation window (registry tag `mae_1h`). `mae_ratio_pooled` is the same ratio over all cities together. The backend asks the model server for those forecasts in one call and caches the result per replay hour and champion version. The MAE ratios are `null` until 24 replayed hours exist, and also when the model server or the champion's `mae_1h` is not available; PSI does not need the model, so drift detection keeps working without it.

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
`reason`: string, 1-200 chars. The cutoff is set to the current `sim_time`. `request_id` is `rt-` plus the wall-clock time to the second. The request is saved with `trigger: "manual"`.

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
the backend creates a retrain request with reason `drift_alert:<alertname>`, `trigger: "drift_alert"` and a `drift`
snapshot (`cities_exceeding`, `psi_max`, `mae_ratio_pooled` at that moment), unless one was created in the last
`RETRAIN_COOLDOWN_MIN` (30) minutes or one is still queued or running. A drift alert is also ignored while a drift
episode is open: an episode opens when a drift alert creates a request and closes when the drift rule has been false for
`drift.episode_clear_hours` (72) simulated hours in a row (state in `<OPS_DIR>/episode.json`). All alerts are logged.
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

The model is one MLflow pyfunc (`src/pipeline/aq_model.py`) that holds both horizon models and picks one per row from `horizon_h`. Rows come back in the order they were sent. `pm25` is in µg/m³, rounded to 2 decimals and never below 0. A request with a missing column or a `horizon_h` other than 1 or 24 is rejected with an error. `model_version` is read from the environment variable `AQ_MODEL_VERSION`, which the model-server wrapper sets from the registry version it loaded (`src/model_server/supervisor.py`). It is `unversioned` when the variable is not set. The input columns must be integers for `horizon_h`, `city_code`, `hour`, `dow`, `month` and `is_weekend`, and numbers (null allowed) for the rest. The same list is the MLflow model signature.

**How the model server is laid out (Stage 9).** The container runs one entry point, `python -m src.model_server.serve`, which starts three things.

| Part | Port | What it does |
|------|------|--------------|
| Proxy (`proxy.py`) | 5001 (public) | Forwards `/invocations` and `/ping` to MLflow unchanged, times `/invocations` and counts rows per horizon. Answers 503 `{"error": "model unavailable"}` if MLflow cannot be reached, or `{"error": "no model loaded"}` before the first champion is loaded. Errors from MLflow (for example 400 for a bad horizon) are passed through with their status. |
| `mlflow models serve` | 5002 or 5003 (internal, 127.0.0.1) | The real model API. One worker. The watcher uses the port that is free. |
| Metrics (`prometheus_client`) | 8001 | `/metrics` with the three model-server metrics in section 5. |

The watcher (`supervisor.py`) reads the `champion` alias every `POLL_SECONDS` (30). If the version changed it downloads the package, starts MLflow on the spare port, waits for `/ping`, switches the proxy and then stops the old process. If the new model does not start within 90 s, the old model keeps serving and the next poll tries again. A rollback is the same event: the alias moves, so the watcher swaps to the older version.

## 5. Prometheus metrics

| Component | Metric | Type | Labels |
|-----------|--------|------|--------|
| backend | `aq_http_requests_total` | counter | `method, path, status` |
| backend | `aq_http_request_duration_seconds` | histogram | `method, path` |
| backend | `aq_forecast_pm25` | gauge | `city, horizon_h` |
| backend | `aq_drift_psi` | gauge | `city` |
| backend | `aq_drift_threshold` | gauge | `city` |
| backend | `aq_drift_cities_exceeding` | gauge | — |
| backend | `aq_rolling_mae_ratio` | gauge | `city` |
| backend | `aq_rolling_mae_ratio_pooled` | gauge | — |
| backend | `aq_drift_detected` | gauge (1 = the `any_drift` rule above is true) | — |
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
| MLflow server (`:5000/metrics`) | `mlflow_http_request_total`, `mlflow_http_request_duration_seconds` | counter, histogram | `method, status` |
| backend, model server, frontend | `process_resident_memory_bytes`, `process_cpu_seconds_total` | gauge, counter | — |
| host | node-exporter defaults | — | — |
| Prometheus, Alertmanager, Grafana, Pushgateway | their own built-in metrics | — | — |

Prometheus scrapes every target above every 15 s (`monitoring/prometheus.yml`), the Pushgateway with `honor_labels: true` so the pushed `job="aq_pipeline"` and `stage` labels stay. The frontend exporter is started by `src/frontend/main.py` before Streamlit, so it answers from boot and not only after the first page visit. `python -m scripts.push_stage_metrics [--url URL]` re-pushes the latest record of every stage from `reports/stage_metrics/*.json`, with the stage's own end time as `aq_pipeline_last_success_timestamp`, for a batch that ran while the Pushgateway was down.

Grafana (`monitoring/grafana/`) is provisioned from files: the Prometheus data source (uid `prometheus`) and two dashboards in the folder "AQ", both refreshing every 15 s. `aq-service` (the home dashboard) has the overview (model versions, drift, replay clock, firing alerts, targets up), backend request rate, latency p50/p95/p99 and error rate, forecasts and model-server rate and latency, PSI per city against its threshold, the MAE ratios, frontend views and call latency, and memory and CPU. `aq-pipeline` has stage duration, rows per second and status, the last success and last push, retrain requests, and MLflow request rate and latency. Anonymous users get the Viewer role; the admin password is `GRAFANA_ADMIN_PASSWORD`.

Alert rules (`monitoring/alerts.yml`):

| Alert | Expression (summary) | for | labels |
|-------|----------------------|-----|--------|
| `PM25DriftHigh` | `aq_drift_detected == 1` | 1m | `action=retrain`, `severity=critical` |
| `ForecastErrorHigh` | `aq_rolling_mae_ratio_pooled > 1.5` | 5m | `severity=warning` (no retrain) |
| `BackendErrorRateHigh` | 5xx share of `aq_http_requests_total` > 5% over 5m | 2m | — |
| `ModelServerErrors` | `increase(aq_model_server_errors_total[5m]) > 0` | 1m | `severity=warning` |
| `TargetDown` | `up == 0` | 1m | — |
| `PipelineStageFailed` | `aq_stage_status == 0` | 0m | — |

## 6. Files and shared volumes

| Path | Writer | Reader | Content |
|------|--------|--------|---------|
| `data/interim/*.parquet` | ingest | validate, features | Typed copies of the raw CSVs |
| `data/features/train.parquet` | features | train, evaluate | Spark Parquet folder. One row per city and hour with `Datetime <= cutoff`: `City`, `Datetime`, the stored feature columns (section 4 without `horizon_h`), `pm25` (observed value at the hour) and targets `y_1h`, `y_24h`. A target is null if its hour is missing or falls after the cutoff, so training never sees the future. Hours missing in the source are present as rows with null values. |
| `data/features/serving.parquet` | features | backend (ro) | Same columns as `train.parquet`, for every hour 2020-01-01 00:00 .. 2020-06-30 23:00 and the 7 cities (4,368 rows per city). Features are causal (past only). `pm25`, `y_1h` and `y_24h` are the actuals the backend reveals when its replay clock passes them. `y_24h` is null for the last 23 hours because the data ends on 2020-07-01 00:00. |
| `reports/baseline_stats.json` | features | train (logged as `drift_baseline.json`), backend | Same-season PSI reference for `pm25_lag_1`. Top level: `feature`, `reference`, `years` (default `[2016, 2019]`), `replay_start`, `replay_hours`, `week_hours` (168), `n_bins`, `bin_rule`, `week_rule`, `cities`. Each city has `years` (years that had data) and `weeks`: a list of `{week, n, edges, proportions}`, one block per 168 replay hours (14 blocks for the default replay). The reference values of block `k` are `pm25_lag_1` at the same calendar hours of the earlier years (aligned on the replay start's month and day). Bin index of a value is the number of edges `e` with `e <= value`. A live window whose last hour is replay hour `h` uses block `h // 168`. |
| `reports/drift_thresholds.json` | features | backend, `scripts/replay.py` | Per-city PSI threshold. Top level: `feature`, `percentile` (95), `years`, `blocks` (`[1, 13]`), `rule`, `cities`. Each city has `psi_threshold`, `n_values` (how many normal weeks were scored) and `years`. The threshold is the 95th percentile of the city's PSI in normal weeks: every block 1 to 13 of every reference year compared with the same block of the other years (leave-one-year-out), computed with `src/monitoring/drift.py`. A city with fewer than 3 reference years (Kolkata) has no entry and does not vote. |
| `reports/drift_replay.json` | `scripts/replay.py` | docs | Result of the offline acceptance replay: `rule`, `min_cities`, `thresholds`, `normal_years` and `lockdown` (each with `drift_hours`, `episodes`, `first_drift`, `max_cities_exceeding`, `hours_with_at_least_k_cities`, `exceed_hours_per_city`), `acceptance` (`lockdown_triggers`, `normal_weeks_quiet`, `false_alarm_hours`, `passed`) and, with `--with-mae`, `mae_ratio_pooled_72h` per year. |
| `reports/validation.json` | validate | console, docs | `{status, n_checks, n_passed, n_warnings, n_failed, checks[], stats}`; each check is `{table, check, status: pass/warn/fail, detail, value}` |
| `reports/eda/*.csv` | `python -m src.pipeline.eda` (manual, not a DVC stage) | `scripts/plot_eda.py`, docs | Small aggregates for `docs/eda.md` |
| `reports/runs.jsonl` | every stage (via `stage_runner`) | backend `/pipeline/*` | One JSON line per stage execution: `{run_id, trigger, stage, status, started_at, duration_s, rows_in, rows_out, rows_per_sec, error, git_commit, cutoff}` |
| `ops/requests/<id>.json` | backend, ops runner | ops runner, backend | Written by the backend: `{request_id, reason, cutoff, created_at, status: "queued", trigger, drift}`. The runner sets `status` to `running` and adds `started_at` and `run_id` (the pipeline run id), then sets the final `status`: `done` (the gate decided: `promoted` true or false), `failed` (with `error`) or `rolled_back` (the new champion failed the smoke check; `rolled_back_to`). It also adds `cutoff` in params format, `promoted`, `version`, `mlflow_run_id`, `reasons`, `smoke` and `finished_at`. Files are replaced atomically. A request left `running` by a crashed runner is marked `failed` when the runner starts again. |
| `ops/logs/<id>.log` | ops runner | people | Full output of the `dvc repro` run for one request. |
| MLflow artifacts per run | train | backend, model server | The model as an MLflow logged model linked to the run (pyfunc with `meta.json` and, per horizon, `h1.txt` / `h24.txt` for a LightGBM booster or `h1.joblib` / `h24.joblib` for a Ridge pipeline; `meta.json` has `kinds`, for example `{"1": "lightgbm", "24": "ridge"}`; its URI is `model_uri` in `reports/train_metrics.json`), `drift_baseline.json`, `per_city_mae.csv`, `feature_importance.png`, `residuals.png`, `params_resolved.json`, `environment_pins.txt` |
| MLflow tags and metrics per run | train | register, console | Tags: `git_commit` (full hash), `git_dirty` (true if code or settings differ from the commit; `dvc.lock` and `reports/` are ignored because the pipeline rewrites them), `dvc_data_md5` (raw data version), `features_md5` (hash of the values in `train.parquet`, independent of file layout), `cutoff`, `trigger`, `pipeline_run_id`, `chosen_1h`, `chosen_24h` (`ridge` or `lightgbm`), and after the register stage `promotion` (`promoted` or `rejected`), `registry_version` or `rejected_reasons`. Metrics: `<model>_mae_<h>h`, `<model>_rmse_<h>h` and `<model>_mae_<h>h_<city>` for `persistence`, `seasonal_naive`, `ridge`, `lightgbm`; `<model>_mean_mae`; `ratio_lightgbm_to_best_baseline_<h>h`; `best_baseline_mae_<h>h`; `chosen_mae_<h>h` and `ratio_chosen_to_best_baseline_<h>h` (the served model of the horizon); after the register stage also `eval_candidate_mean_mae` and `eval_champion_mean_mae`; `lightgbm_mae_<h>h_high_pm25`; `fit_seconds_*`; `drift_*` when a drift trigger file exists. |
| `reports/drift_trigger.json` | ops runner | train | Optional, gitignored, deleted after the run. The `drift` snapshot of a `drift_alert` request, for example `{"cities_exceeding": 4, "psi_max": 6.07, "mae_ratio_pooled": 0.83}`. Numbers are logged as `drift_<name>` metrics. |
| `reports/train_metrics.json` | train | register, evaluate | `run_id`, `model_uri`, `experiment`, `git_commit`, `git_dirty`, `dvc_data_md5`, `features_md5`, `cutoff`, `eval_window`, `mean_mae` per model plus `chosen` (mean MAE of the served models), `ratio_to_best_baseline` per horizon (LightGBM), and per horizon `n_train`, `n_eval`, `metrics` per model, `best_baseline`, `chosen` (`model`, `mae`, `ratio_to_best_baseline`), `high_value`. |
| `reports/eval.json` | evaluate | test, register | `cutoff`, `eval_window`, `candidate` (`run_id`, `model_uri`, `mean_mae`, and per horizon `mae`, `rmse`, `n`, `model`, `best_baseline`) and `champion` (`version`, `mean_mae`, per horizon `mae`, `rmse`, `n`), or `null` when there is no champion yet. Both are scored through the MLflow package on the same rows. |
| `reports/gate.json` | test | register | `passed`, `reasons[]`, `first_model`, `ratio_to_best_baseline` per horizon, `max_ratio`, `candidate_mean_mae`, `champion_mean_mae`, `candidate_run_id`. |
| `reports/register.json` | register | console | `promoted`, `version` (null when rejected), `champion_before`, `mlflow_run_id`, `reasons[]`, `cutoff`, `git_commit`. |
| MLflow registry `aq-pm25` | register, `scripts/rollback.py` | model server, backend | One version per promoted candidate. Aliases `champion` (served) and `previous` (the champion before the last promotion). Version tags: `cutoff`, `git_commit`, `dvc_data_md5`, `mae_1h`, `mae_24h`, `model_1h`, `model_24h`. |

## 7. Pipeline stage contracts (`dvc.yaml`)

| Stage | Command | deps | outs / metrics |
|-------|---------|------|----------------|
| ingest | `python -m src.pipeline.ingest` | `data/raw`, `src/pipeline/ingest.py`, `src/common`, params `paths, spark, ingest` | `data/interim/` (one Parquet folder per table) |
| validate | `python -m src.pipeline.validate` | `data/interim/`, `src/pipeline/validate.py`, `src/pipeline/ingest.py`, `src/common`, params `paths, spark, cities, replay, validate` | `reports/validation.json` (metric, kept in git; written even when validation fails) |
| features | `python -m src.pipeline.features` | `data/interim/`, `reports/validation.json` (the stage refuses to run unless its `status` is `passed`), `src/pipeline/features.py`, `src/monitoring/drift.py`, `src/common`, params `paths, spark, cities, cutoff, replay, features` | `data/features/`, `reports/baseline_stats.json`, `reports/drift_thresholds.json` (both kept in git) |
| train | `python -m src.pipeline.train` | `data/features/train.parquet`, `reports/baseline_stats.json`, `src/pipeline/train.py`, `modeling.py`, `aq_model.py`, `train_plots.py`, `src/common`, params `paths, cities, cutoff, eval_window_days, train` | `models/candidate/` (MLflow pyfunc model), `reports/train_metrics.json` (kept in git). Also writes one MLflow run to the tracking URI (`MLFLOW_TRACKING_URI`, default `sqlite:///mlflow.db`). |
| evaluate | `python -m src.pipeline.evaluate` | `models/candidate/`, `data/features/train.parquet`, `reports/train_metrics.json`, `src/pipeline/evaluate.py`, `registry.py`, `modeling.py`, `src/common`, params `paths, cutoff, eval_window_days, promotion.model_name` | `reports/eval.json` (metric, kept in git). Reads the `champion` alias from the registry, which DVC does not track. |
| test | `python -m src.pipeline.test_gate` | `reports/eval.json`, `src/pipeline/test_gate.py`, `src/common`, params `paths, promotion.max_ratio_to_baseline` | `reports/gate.json` (metric, kept in git). A rejection is a success of the stage with `passed: false`. |
| register | `python -m src.pipeline.register` | `reports/gate.json`, `reports/eval.json`, `reports/train_metrics.json`, `models/candidate/`, `src/pipeline/register.py`, `registry.py`, `src/common`, params `paths, cutoff, promotion.model_name` | `reports/register.json` (metric, kept in git). Creates a registry version and moves the aliases only when the gate passed. |

`python -m scripts.replay [--with-mae]` runs the drift acceptance replay (section 6, `reports/drift_replay.json`); its exit code is 0 only if the test passed.

`python -m src.ops.runner [--once] [--poll S]` is the ops runner on the host. For each queued request it checks free memory, sets `cutoff` in `params.yaml` to the request's cutoff (it must be after the current cutoff and not after the replay end), writes `reports/drift_trigger.json` for a drift request, runs `dvc repro` with `PIPELINE_TRIGGER` and `PIPELINE_RUN_ID`, reads `reports/register.json` and, after a promotion, runs the smoke check: it asks the model server for a 1 h forecast of one stored row until the new version answers with a finite value of 0 or more. If that does not happen within `SMOKE_TIMEOUT_S`, it moves `champion` back to `previous`.

`python -m scripts.rollback [--version N] [--list]` moves `champion` to `previous` (or to version N) and `previous` to the old champion. It is the code behind `POST /ops/rollback`.

## 8. Environment variables

| Variable | Used by | Default |
|----------|---------|---------|
| `BACKEND_URL` | frontend | `https://backend:8000` |
| `BACKEND_CA_FILE` | frontend | unset (system CAs). Compose sets `/certs/ca.crt`, the CA that signed the backend's certificate. |
| `UI_METRICS_PORT` | frontend | `8502` |
| `MLFLOW_URL`, `GRAFANA_URL`, `PROMETHEUS_URL` | frontend (console links only) | `http://localhost:5000`, `:3000`, `:9090` |
| `OPS_API_KEY` | backend, alertmanager | — (required, in `.env`). The frontend does not read it: the operator types the key into the console, which sends it only to `/ops/*`. |
| `MODEL_SERVER_URL` | backend | `http://model-server:5001` |
| `MLFLOW_TRACKING_URI` | backend, pipeline, model server | `http://mlflow:5000` |
| `MLFLOW_HTTP_REQUEST_MAX_RETRIES`, `MLFLOW_HTTP_REQUEST_TIMEOUT` | backend | `2`, `10` (s). MLflow's own defaults retry for minutes, so a registry call the caller had given up on could still be applied much later. |
| `MODEL_NAME`, `POLL_SECONDS` | model server | `aq-pm25`, `30` |
| `MODEL_PORT`, `METRICS_PORT` | model server | `5001`, `8001` |
| `REPLAY_SPEED_HPS` | backend | `1.0` |
| `RETRAIN_COOLDOWN_MIN` | backend | `30` |
| `OPS_DIR` | backend, ops runner | `<project>/ops` (request files go to `<OPS_DIR>/requests/`, run logs to `<OPS_DIR>/logs/`) |
| `BACKEND_PORT` | backend | `8000` |
| `DRIFT_MIN_CITIES` | backend | `drift.min_cities` in `params.yaml` (4) |
| `drift.episode_clear_hours` | backend | `72` simulated hours (`params.yaml` only, no env override) |
| `DRIFT_MAE_RATIO` | backend | `drift.mae_ratio_warn` in `params.yaml` (1.5); warning only |
| `MODEL_SERVER_URL` | ops runner (smoke check) | `http://localhost:5001` |
| `SMOKE_TIMEOUT_S` | ops runner | `180` (the watcher polls every 30 s and a start can take up to 90 s) |
| `RUN_TIMEOUT_S` | ops runner | `3600` |
| `RUNNER_MIN_FREE_MB` | ops runner | `2500` (the batch does not start with less memory available) |
| `TLS_CERT_FILE`, `TLS_KEY_FILE` | backend | `/certs/server.crt`, `/certs/server.key`. If either file is missing the backend serves plain HTTP and logs a warning. |
| `CERT_DIR` | `scripts/make_certs.sh` | `certs` (gitignored). The script takes extra host names or IPs as arguments and adds them to the certificate. |
| `PUSHGATEWAY_URL` | pipeline | `http://pushgateway:9091` in the pipeline container; `http://localhost:19091` for the ops runner and `scripts.push_stage_metrics` on the host |
| `PUSHGATEWAY_HOST_PORT` | compose | `19091` |
| `GRAFANA_ADMIN_PASSWORD` | grafana | — (required, in `.env`) |

## 9. Frontend pages

The Streamlit frontend (`https://<host>/` through the TLS proxy; Streamlit itself listens on `:8501` inside the compose network only) has two pages, each with its own URL path.

| Path | Page | Who it is for |
|------|------|---------------|
| `/forecast` | Forecast | everyone |
| `/console` | Pipeline console | the operator (ops buttons need the API key) |
| `/` | redirects to `/forecast` | |

Streamlit always serves its default page at `/` and ignores that page's `url_path`. My first version made Forecast the default, so `/forecast` showed "Page not found". The default page is now a hidden redirect, and the sidebar links to the two real pages.
