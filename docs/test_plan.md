# Test Plan

This plan says what I test, how, on what machine, and what counts as "done". The results are in `docs/test_report.md`.

## 1. Scope

**In scope.** Everything I wrote and run:

- the 7-stage DVC pipeline (ingest, validate, features, train, evaluate, test, register) and the shared helpers in `src/common/`
- the model package, the promotion gate, the registry aliases and rollback
- the model server (proxy and watcher), the FastAPI backend and every endpoint in `docs/LLD.md`
- drift detection, the replay script and the ops runner
- the Streamlit frontend (both pages and the backend client)
- the monitoring configuration (Prometheus scrape jobs, alert rules, Grafana dashboards)
- the security set-up (certificates, HTTPS, API key, secrets, non-root containers)
- the CI script and the pre-commit hook

**Out of scope.** Libraries I did not write (Spark, MLflow, LightGBM, Streamlit, Prometheus), load testing beyond serial latency, other browsers and real phones, and the amd64 image, which I cannot run on this ARM VM.

## 2. Test levels

**Unit tests.** One pytest file per module in `tests/`. They test pure functions and classes with small, made-up inputs and fakes for the network: the backend gets a fake model server and a fake registry, and the frontend gets a fake backend. They run in seconds and need no services.

**Integration tests.** These are also in pytest, but they use the real thing on a small scale. Spark tests start a real local Spark session (one per test session) on tiny DataFrames. Registry and promotion tests use a real MLflow tracking store in a temporary SQLite file. The TLS tests start a real HTTPS server with certificates made by `scripts/make_certs.sh`. The frontend page tests run the real Streamlit pages through `AppTest`. The CI tests run `scripts/ci.sh` as a subprocess with a fake `docker`. None of them touch `data/raw`, `mlflow.db` or the running stack.

**End-to-end checks.** These run on the real data and the real compose stack. Some are scripts with a pass/fail exit code (`scripts/replay.py`, `scripts/ci.sh --repro`, `promtool test rules`). The others are drills I run by hand with `curl` and record with timestamps: drift to retrain, alert firing, rollback, hot swap, TLS, cold start. I list them as E2E cases in section 6 so they are numbered like the rest.

**Static checks.** `ruff check` and `ruff format --check` (PEP 8, docstrings, imports), and `promtool check config` and `check rules` for Prometheus.

## 3. Test environment

| Item | Value |
|------|-------|
| Machine | Ubuntu 26.04.1 LTS VM, ARM64 (aarch64), 4 CPU, 7.2 GB RAM |
| Python | 3.12.15 in `.venv`, made with `uv` from `uv.lock` |
| Test tools | pytest 9.1.1, ruff 0.17.1, promtool from `prom/prometheus:v3.5.0` |
| Main libraries | PySpark 3.5.9 (Java 17 on the host), MLflow 3.17.1, LightGBM 4.7.0, scikit-learn 1.9.1, FastAPI 0.151.0, Streamlit 1.66.0, DVC 3.67.1 |
| Containers | Docker 29.8.2, Compose v5.6.0, `serve` profile (10 containers) |
| Data | CPCB 2015-2020, DVC version `7921cce1dbe07b5b8c33ffd85e4a34b4.dir` |
| Browser | none that works headless on this VM, so I check the pages through `AppTest` and `curl`; the screenshots are taken by hand on my desktop |

The serve stack and the batch profile never run at the same time (8 GB limit). `scripts/ci.sh --repro` refuses to start while the serve stack is up.

## 4. How to run

```
scripts/ci.sh                         # ruff, pytest (JUnit XML), dvc status, dvc status -c
scripts/ci.sh --repro                 # + dvc repro and dvc push (stop the serve stack first)
.venv/bin/python -m scripts.replay    # drift acceptance test, exit code 0 = passed
docker run --rm --entrypoint promtool -v $PWD/monitoring:/m:ro prom/prometheus:v3.5.0 test rules /m/alerts_test.yml
```

Entry criterion for a test run: the code is committed or the diff is known, and `uv sync --frozen` has been run. Exit criterion: every acceptance criterion in section 5 is met, or the report says plainly which one is not.

## 5. Acceptance criteria

| ID | Criterion | How it is measured | Pass if |
|----|-----------|--------------------|---------|
| AC-1 | The served model beats persistence at both horizons | MAE of the champion and of persistence on the same evaluation window, from the MLflow run and `reports/eval.json` | champion MAE < persistence MAE at 1 h **and** at 24 h |
| AC-2 | The forecast API is fast enough | 300 serial `GET /forecast` calls over HTTPS on the live stack, rotating through the 7 cities, with a reused and with a new connection | p95 < 300 ms in both cases, and every call returns 200 |
| AC-3 | Drift fires on the lockdown replay and not on normal weeks | `python -m scripts.replay`: every hour of 25 Mar to 30 Jun in 2016-2019 and 2020 | at least 1 drift hour in 2020 **and** 0 drift hours in 2016-2019; exit code 0 |
| AC-4 | The promotion gate rejects a model that does not improve | `test` stage on a real `dvc repro` where the candidate ties the champion, plus unit tests for a worse candidate and for a baseline ratio above 1.02 | `gate.json` says `passed: false` with a reason, nothing is registered, the champion is unchanged |
| AC-5 | Rollback restores the previous champion | `POST /ops/rollback` on the live stack, then forecasts until the model version changes; then the same again to undo | the alias moves to `previous`, the forecast answers with that version, and the undo restores the original champion |
| AC-6 | Every result can be reproduced from a git commit and an MLflow run ID | Take the champion's run ID, read its tags (commit, cutoff, data version), rerun the pipeline from a clean commit with that cutoff, compare | same data and feature hashes, same MAE, and the same model files byte for byte |
| AC-7 | The code is clean and the suite passes | `scripts/ci.sh` | ruff and format pass, 0 failed and 0 errors in `junit.xml`, `dvc status` and `dvc status -c` clean |

## 6. Test cases

**Type:** U = unit, I = integration (real Spark, MLflow, TLS, Streamlit or a subprocess), E2E = end to end on real data or the live stack. The pytest cases name the test functions they cover. Every test function in `tests/` belongs to one case.

### 6.1 Pipeline and data

| ID | What it checks | Type | Tests | Expected result |
|----|----------------|------|-------|-----------------|
| TC-01 | Settings and logging helpers | U | `test_common.py` (all) | `params.yaml` loads; a missing file, bad YAML or a non-mapping raises `ConfigError`; `.env` never overrides a set variable; log levels apply |
| TC-02 | Stage run records | U | `test_stage_runner.py` (all) | success writes `runs.jsonl` and `stage_metrics/<stage>.json` with rows/sec; a failure is recorded with its message and re-raised as `PipelineStageError`; a dead Pushgateway is only a warning |
| TC-03 | Spark ingest, CSV to Parquet | I | `test_ingest.py` (all) | row count of Parquet equals CSV lines; BOM header handled; a malformed row stops the run (FAILFAST); missing file and unknown table raise |
| TC-04 | pandas benchmark counts | U | `test_bench_pandas.py` | same row counts as Spark; missing file raises |
| TC-05 | Validation rules | U | `test_validate.py`: `test_params_have_a_ceiling_*`, `test_good_profile_*`, `test_schema_mismatch_fails`, `test_empty_nulls_and_duplicates_fail`, `test_ceiling_message_*`, `test_negative_values_fail`, `test_time_range_outside_fails`, `test_off_hour_*`, `test_unknown_bucket_*`, `test_empty_table_*`, `test_check_cities_*`, `test_check_stations`, `test_build_report_counts_failures` | every hard rule fails with a message naming column, limit and row count; unknown bucket and high missing share only warn |
| TC-06 | Validation on Spark | I | `test_validate.py`: `test_profile_table_counts`, `test_validate_all_*` | good data passes all checks; an impossible value fails the stage; missing tables are reported |
| TC-07 | Feature correctness | I | `test_features.py`: `test_grid_adds_missing_hours`, `test_lags_count_hours_not_rows`, `test_forward_fill_limit`, `test_targets_use_raw_values_*`, `test_rolling_windows`, `test_calendar_features`, `test_features_never_use_the_future` | lags count hours, gaps over 3 h stay null, targets are never filled, and changing a later reading changes no earlier row |
| TC-08 | Cutoff and serving split | I | `test_features.py`: `test_train_set_hides_targets_after_cutoff`, `test_serving_set_is_inclusive`, `test_replay_hours` | no training target lies after the cutoff; serving covers 2020-01-01 to 2020-06-30 |
| TC-09 | Drift reference and thresholds made by the features stage | I | `test_features.py`: `test_baseline_*` (5), `test_drift_thresholds_*` (2) | same calendar hours of earlier years only; at least 100 values per block; a city needs 3 reference years to get a threshold |
| TC-10 | Features stage as a whole | I | `test_features.py`: `test_run_features_end_to_end`, `test_features_refuse_to_run_without_a_passed_validation` | writes train, serving, baseline and thresholds; refuses to run if `validation.json` is missing, failed or unreadable |
| TC-11 | Feature columns match the LLD | U | `test_schema.py` (all) | the column list in code equals the LLD table, in order, with no duplicates |
| TC-12 | EDA aggregates and figures | I | `test_eda.py` (all), `test_plot_eda.py` | each aggregate has the expected rows; 6 figures are drawn |
| TC-13 | Data and code versioning | U/I | `test_versioning.py` (all) | the data hash ignores file layout and row order and changes when a value changes; commit and dirty flag are right in a temporary git repo; pipeline outputs do not make the tree dirty |
| TC-14 | DVC and MLproject set-up | U | `test_dvc_setup.py` (all) | `data/raw` tracked by DVC and not in git; the remote is a local path; `dvc.yaml` has the 7 stages in order; `python_env.yaml` matches `uv.lock` |

### 6.2 Models, gate and registry

| ID | What it checks | Type | Tests | Expected result |
|----|----------------|------|-------|-----------------|
| TC-15 | Evaluation protocol | U | `test_modeling.py`: `test_split_*` (2), `test_recency_weights_*`, `test_baseline_predictions_by_horizon` | training rows whose target falls in the window are purged; weights halve every half-life; baselines are right per horizon |
| TC-16 | Ridge and LightGBM handle gaps | U | `test_modeling.py`: `test_ridge_*` (2), `test_lgbm_frame_*`, `test_lightgbm_accepts_nulls_and_trains` | Ridge imputes with a missing flag that changes the prediction; LightGBM trains on nulls |
| TC-17 | Scores and model choice | U | `test_modeling.py`: `test_error_metrics_*`, `test_per_city_table_*`, `test_choose_model_*` | MAE, RMSE and high-value error are right; a tie goes to LightGBM |
| TC-18 | Training is repeatable | U/I | `test_modeling.py::test_lightgbm_training_is_repeatable`, `test_train.py::test_run_train_is_repeatable_for_a_new_cutoff` | two fits give identical predictions |
| TC-19 | Train stage logs beyond autolog | I | `test_train.py` (other 7), `test_train_plots.py` | the run has commit, dirty flag, data hash, per-city MAE, plots and env file; the model signature matches the LLD; too few rows fail clearly |
| TC-20 | Model package | U | `test_aq_model.py` (all) | predicts both horizons in input order, never negative, accepts nulls, holds Ridge or LightGBM per horizon, refuses unknown kinds and missing columns |
| TC-21 | Promotion gate rule | U | `test_gate.py` (all) | ratio limit 1.02 is inclusive and not relaxed; a candidate must be strictly better than the champion; a rejection is `passed: false`, not a stage failure |
| TC-22 | Registry aliases | I | `test_registry.py` (all) | first promotion sets `champion`; the next moves the old one to `previous`; rollback can itself be rolled back; unknown version, no previous and "already champion" raise and change nothing; with MLflow unreachable, or an alias move that fails, rollback raises `RegistryUnavailableError` (not "No previous version"), while the serving lookup still returns None |
| TC-23 | Evaluate, test and register together | I | `test_promotion_flow.py` (all) | first model promoted, an equal candidate rejected; the version has its tags and loads by alias; stale or mismatched reports are refused |
| TC-24 | Rollback script | I | `test_rollback_script.py` (all) | moves `champion` back; a missing version exits with an error; `--list` shows versions |

### 6.3 Serving and backend

| ID | What it checks | Type | Tests | Expected result |
|----|----------------|------|-------|-----------------|
| TC-25 | Model-server proxy | U | `test_model_server.py`: `test_count_rows_*` (2 functions), `test_proxy_*` (3), `test_ping_is_forwarded` | forwards and counts rows per horizon; errors pass through uncounted; 503 when nothing is loaded or upstream is down |
| TC-26 | Model-server watcher | U | `test_model_server.py`: `test_sync_*` (2), `test_failed_load_keeps_the_old_model`, `test_wait_ready_*` | loads the champion, swaps on a new one, keeps the old model if the new one fails to start |
| TC-27 | Health, cities, AQI table | U | `test_backend.py`: `test_health_ok_and_degraded`, `test_cities`, `test_aqi_categories_match_hld`, `test_categorize_edges` | 7 cities; category edges follow CPCB (30.5 is Good, 31 Satisfactory) |
| TC-28 | Forecast answer | U | `test_backend.py`: `test_forecast_shape_and_values`, `test_forecast_null_observed_and_null_feature` | both horizons with category, colour, advice, model version, run ID and commit |
| TC-29 | Bad input and failures never give a raw 500 | U | `test_backend.py`: `test_forecast_unknown_city_is_404`, `test_forecast_missing_city_is_422`, `test_forecast_model_down_is_503`, `test_forecast_no_data_*`, `test_unknown_route_and_method_use_error_body`, `test_unexpected_error_becomes_500_without_details` | 404, 422 and 503 with the LLD error body; an internal crash is a generic 500 with no traceback |
| TC-30 | Pipeline endpoints | U | `test_backend.py`: `test_pipeline_*` (4), `test_registry_failure_does_not_break_forecast` | stages, runs and models as in the LLD; bad lines skipped; a dead registry does not stop forecasts |
| TC-31 | API key on ops endpoints | U | `test_backend.py`: `test_ops_requires_key` (30 cases), `test_empty_key_refused`, `test_settings_from_env_requires_key` | 401 without a key, with a wrong key, `Basic` or no `Bearer`, on all six ops calls; the backend will not start without a key |
| TC-32 | Replay endpoints and clock | U | `test_backend.py`: `test_replay_*` (3), `test_clock_advances_*` | start, stop and reset work; bad bodies are 422; the clock follows the speed and stops at the end |
| TC-33 | Retrain queue and rollback endpoint | U | `test_backend.py`: `test_retrain_*` (2), `test_rollback_default_named_and_missing`, `test_rollback_with_registry_down_is_503`, `test_openapi_lists_503_for_rollback`, `test_queue_*` (2) | one request at a time; 30-minute cooldown; rollback to previous or a named version; unknown version is 400; registry down is 503 `REGISTRY_UNAVAILABLE` and the OpenAPI spec lists it |
| TC-34 | Alert webhook and drift episodes | U | `test_backend.py`: `test_alerts_*` (4), `test_episode_gate_closes_after_quiet_period` | only firing alerts with `action=retrain` create a request; one retrain per drift episode; the episode closes after 72 quiet simulated hours |
| TC-35 | Backend metrics and LLD match | U | `test_backend.py`: `test_metrics_*` (2), `test_lld_lists_the_backend_routes`, `test_openapi_documents_the_lld_error_responses`, `test_ops_drift_*` (2), `test_model_client_*`, `test_store_missing_file_raises` | every LLD metric is exported; path labels are route templates; every route is documented in the LLD; `/openapi.json` shows the LLD error body and codes |
| TC-36 | Drift maths | U | `test_drift.py` (all) | PSI is 0 for the same data and grows with the shift; leave-one-year-out leaves the year out; only voting cities count; no drift before a full window |
| TC-37 | Backend drift report | U | `test_backend_drift.py` (all) | two shifted cities trigger drift when 2 are needed; MAE ratio is reported but not part of the rule; missing reference files give no votes |
| TC-38 | Replay acceptance logic | U | `test_replay_script.py` (all) | consecutive drift hours group into episodes; a year that agrees with the others stays quiet |
| TC-39 | Ops runner | U | `test_ops_runner.py` (all) | moves the cutoff, runs the pipeline, smoke-checks a promotion, rolls back when the smoke check fails, refuses below 2,500 MB free, ignores a stale `register.json`, marks interrupted runs failed; stops the frontend and Grafana before the batch and starts exactly those again after it, also when the pipeline fails or memory is short; a docker error never fails a request |

### 6.4 Frontend, monitoring, security, CI

| ID | What it checks | Type | Tests | Expected result |
|----|----------------|------|-------|-----------------|
| TC-40 | Backend client | U | `test_frontend.py`: `test_client_*` (5) | reads `BACKEND_URL` and `BACKEND_CA_FILE`; sends the key only when given; maps error bodies to codes; counts and times calls |
| TC-41 | Display helpers | U | `test_frontend.py`: `test_text_color_*`, `test_nice_time_*`, `test_card_html_*`, `test_dag_dot_*`, `test_count_runs` | readable text colour on every AQI colour; advice is HTML-escaped; DAG nodes coloured by status |
| TC-42 | Forecast page | I | `test_frontend.py`: `test_forecast_page_*` (7) | cards for the chosen city; the 2020 demo note; "Demo clock is paused" when the replay is stopped and "Replay running" when it runs (from `GET /health`), and no note but still the cards when `/health` fails; a friendly sentence when the backend or the model is down |
| TC-43 | Pipeline console | I | `test_frontend.py`: `test_console_*` (3) | no ops buttons until a key the backend accepts; a wrong key shows an error and no buttons; with a key, drift shows and retrain posts; failed runs are listed with stage and error; the replay time fits its status box |
| TC-44 | App shell | I | `test_frontend.py`: `test_app_serves_*`, `test_modules_import`, `test_main_starts_exporter_*`, `test_streamlit_config_*` | `/forecast` and `/console` exist; the exporter starts before Streamlit; the developer toolbar is hidden |
| TC-45 | Monitoring configuration | U | `test_monitoring.py` (all), `test_push_stage_metrics.py` (all) | every component scraped every 15 s; alert rules match the LLD; dashboards refresh every 15 s and show every LLD metric; every container has `mem_limit`; retention 2 days; the Pushgateway persists into the folder its user owns |
| TC-46 | TLS | I | `test_security.py`: `test_make_certs_*`, `test_private_keys_*`, `test_client_*` (2), `test_backend_serves_https_*`, `test_backend_falls_back_*`, `test_browser_traffic_*`, `test_backend_and_its_clients_use_https` | the server certificate verifies against the CA; keys are `600`; without the CA the user sees a plain message, not an SSL trace |
| TC-47 | Secrets and non-root | U | `test_security.py`: `test_certs_and_env_are_gitignored`, `test_every_container_runs_as_non_root`, `test_secrets_come_only_from_env_file` | `.env` and `certs/` are gitignored; no container runs as root; every key and password in compose comes from `.env` |
| TC-48 | CI script and hooks | I | `test_ci.py` (all) | valid bash; checks run in order; `--repro` refused while the serve stack runs; hooks are local and cover lint, tests and the data guard |

### 6.5 End-to-end checks

| ID | What it checks | Type | How | Expected result |
|----|----------------|------|-----|-----------------|
| E2E-01 | Cold start of the serve stack | E2E | `docker compose --profile serve down`, then `up -d` | all health checks pass, all 9 Prometheus targets up, 0 restarts, a forecast works with no manual step |
| E2E-02 | Forecast latency over HTTPS (AC-2) | E2E | 300 serial calls, reused and new connections | p95 < 300 ms, all 200 |
| E2E-03 | Frontend reaches the backend only over REST and TLS | E2E | `BackendClient` inside the frontend container with `BACKEND_URL` and the CA | city list and a forecast come back |
| E2E-04 | HTTPS for the browser | E2E | `curl` to `http://localhost`, `:8501`, `https://localhost` with and without the CA | `301` to `https://`; page answers with the CA; refused without it |
| E2E-05 | API key on the live stack | E2E | `curl` to `/ops/drift` and `/ops/rollback` | 401 with no key and with a wrong key, 200 with the key |
| E2E-06 | Drift acceptance replay (AC-3) | E2E | `python -m scripts.replay` | 2016-2019: 0 drift hours; 2020: at least 1; exit 0 |
| E2E-07 | Drift to new model, the whole loop | E2E | lockdown replay with Prometheus, Alertmanager, backend, ops runner and model server | alert fires, one retrain request, `dvc repro` with the new cutoff, gate passes, new champion served, smoke check passes |
| E2E-08 | Alerts on the live stack | E2E | replay for drift; stop the model server for the service alerts | `PM25DriftHigh` creates one retrain request; `ModelServerErrors`, `TargetDown`, `BackendErrorRateHigh` fire and create none |
| E2E-09 | Alert rule unit tests | E2E | `promtool test rules monitoring/alerts_test.yml` | SUCCESS |
| E2E-10 | Gate rejects a non-improving model (AC-4) | E2E | `scripts/ci.sh --repro` with data and cutoff unchanged | candidate ties v4; `gate.json` `passed: false`; champion still v4 |
| E2E-11 | Rollback on the live stack (AC-5) | E2E | `POST /ops/rollback` twice, polling `/forecast` | v4 → v1 served, then v1 → v4 served; unknown version and "already champion" are 400 |
| E2E-12 | Rollback while MLflow is down | E2E | stop the `mlflow` container, `POST /ops/rollback` | 503 `REGISTRY_UNAVAILABLE` ("The model registry (MLflow) is not reachable...") within seconds, and no alias change later |
| E2E-13 | Hot swap drops no request | E2E | promote and roll back while sending a request every 50 ms | 0 failed requests, both versions seen |
| E2E-14 | CI with a full pipeline run | E2E | `scripts/ci.sh --repro` | every step PASS; `dvc status -c` in sync |
| E2E-15 | Reproduce the champion from its run ID (AC-6) | E2E | read v4's tags, rerun at a clean commit with its cutoff, compare | same data hashes, same MAE, identical model files |
| E2E-16 | Pre-commit hook blocks bad code | E2E | stage a file with an unused import and no docstring; stage `.env` | the commit is refused; the guard fails on `.env` and `certs/` |
| E2E-17 | Both pages in a real browser | E2E (manual) | open `https://localhost/forecast` and `/console` on a desktop browser and a narrow window | pages render, colours readable, layout stacks on a narrow screen; screenshots saved in `docs/screenshots/` |
| E2E-18 | Pushgateway keeps its values across a restart | E2E | push a probe metric, wait for the 1-minute save, `docker compose --profile serve down` and `up -d` | the probe is still served |
| E2E-19 | Ops runner pauses and resumes containers | E2E | one `--once` pass of the real runner on the live stack, with a request it must refuse (`RUNNER_MIN_FREE_MB` set very high) | frontend and Grafana stopped, then started again; request `failed` with `paused`; `params.yaml` unchanged; the proxy shows its 503 page meanwhile |
| E2E-20 | Fresh clone to a running stack | E2E | clone into `/tmp`, run `scripts/bootstrap.sh`, `docker compose --profile serve up -d`, smoke-test, then remove the clone | a champion is registered, every health check passes, a forecast answers 200 |
| E2E-21 | MLproject in a fresh environment | E2E | delete `~/.mlflow/envs/`, then `mlflow run . -e main --env-manager uv --experiment-name aq-pm25` | MLflow builds a new environment (from `uv.lock`, which it finds next to `MLproject`), the training run succeeds, and it gives the same MAE and byte-identical LightGBM files as the pipeline's train stage |
| E2E-22 | A failed run shows in the console | E2E | run `validate` with a deliberately lowered PM2.5 ceiling, then restore it | the stage fails with its message; `/pipeline/runs` lists the run as `failed` with that error |
