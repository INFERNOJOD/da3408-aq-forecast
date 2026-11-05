# Rubric Checklist

This maps every line of `docs/rubric.md` (the rubric and the guidelines) to the file, command or screenshot that proves it. I wrote it as an audit at the end of Stage 17, so it starts with what is still missing or weak.

## Still missing or weak

**Missing (needs me):**

1. **Docker Hub (done on 2026-11-05).** All five custom images are published for amd64 and arm64: [aq-frontend](https://hub.docker.com/r/infernogod/aq-frontend), [aq-backend](https://hub.docker.com/r/infernogod/aq-backend), [aq-model-server](https://hub.docker.com/r/infernogod/aq-model-server), [aq-mlflow](https://hub.docker.com/r/infernogod/aq-mlflow) and [aq-pipeline](https://hub.docker.com/r/infernogod/aq-pipeline), each tagged `latest` and `0.1.0`. The full inspect output is in the README, "Docker images".

Index digests and platforms from `docker buildx imagetools inspect <image>:0.1.0` (2026-11-05; `latest` gives the same digests):

| Image | Index digest | Platforms |
|---|---|---|
| `infernogod/aq-frontend` | `sha256:14ec891bb604…` | linux/amd64, linux/arm64 |
| `infernogod/aq-backend` | `sha256:b5a254bd2b86…` | linux/amd64, linux/arm64 |
| `infernogod/aq-model-server` | `sha256:9a701010d9d4…` | linux/amd64, linux/arm64 |
| `infernogod/aq-mlflow` | `sha256:480341e8bcc9…` | linux/amd64, linux/arm64 |
| `infernogod/aq-pipeline` | `sha256:376209d720ec…` | linux/amd64, linux/arm64 |

2. **Screenshots (done on 2026-11-05).** 11 screenshots are in `docs/screenshots/` and linked from the user manual. Screenshot 08 shows the console before the D-5 fix (replay time cut off) and should be taken again. *As of Stage 17:* None are committed. The user manual has 13 marked placeholders (`docs/user_manual.md`). The Grafana dashboards and a fired alert (Stage 14) also need screenshots. The two files in `docs/screenshots/` are early drafts from before the UI was final.
3. **A browser check of both pages (E2E-17, passed on 2026-11-05).** Both pages in Firefox, and the forecast page in responsive mode at iPhone 14 size (393 x 852): it fits and the cards stack. It found D-5, the cut-off replay time, which is now fixed. *As of Stage 17:* The pages are tested through Streamlit's `AppTest` and `curl`, never clicked through on this VM. "Responsive" is not checked at all: Streamlit's column layout should stack on a narrow screen, but I have not looked at it in a narrow window or on a phone.

**Weak (true, but I should be ready to defend it in the viva):**

4. **The drift margin is one city.** Normal years reach 3 cities above threshold and the rule needs 4. The thresholds and the city count were set on the same 2016-2019 weeks I count false alarms on, so "0 false alarms" is in-sample. Hyderabad almost never votes (1 lockdown hour).
5. **The evaluation window is short** (497 rows at 1 h, 336 at 24 h), and the model loses to a baseline in Kolkata and Lucknow.
6. **Auto-rollback after a failed smoke check is tested with fakes only.** The live rollback drill (test report, AC-5) used the manual endpoint.
7. **The ops runner and `scripts/ci.sh --repro` run `dvc repro` on the host, not in the batch container.** The batch container itself ran the full pipeline once on 2026-11-05, with the serve stack stopped (E2E-23): all 7 stages in 74 s, peak memory 2.39 GiB under its 2.5 GiB limit. The first try found defect D-4 (the host uid was unknown inside the image), fixed in compose. I corrected `docs/architecture.md`, which had said the runner starts the container. Since the final audit the runner stops the frontend and Grafana around a retrain and starts them again (E2E-19).
8. **A forecast with MLflow down answers 200 but takes 4.5 s.** The wrong rollback message with MLflow down ("No previous version to roll back to") is fixed since 2026-11-05: it is now 503 `REGISTRY_UNAVAILABLE`, checked live (test report, D-2).
9. **The MLflow container now mounts the whole project folder** (fix D-1 in the test report). It can read `.env`. The pipeline container already had the same mount.
10. **Internal traffic is partly plain HTTP** (model server, MLflow, exporters on the compose network). Only the browser-to-proxy and frontend-to-backend hops, which carry the API key, are TLS.
11. **The reproducibility check rebuilt v4 at a later commit** (`92537ef`, same pipeline code), not at `b2eff79` itself.
12. **Hot swap with zero failed requests was measured outside Docker** (Stage 9).
13. **CI runs when I run it.** There is no server, because cloud CI is not allowed. The pre-commit hook runs on every commit, but `--no-verify` skips it.

## Demonstration [5]

### Web App Front-end UI/UX [3]

| Rubric line | Proof |
|-------------|-------|
| Intuitive for the problem | Forecast page: city dropdown, two colour cards ("In 1 hour", "In 24 hours"), advice, colour guide. `src/frontend/forecast_page.py`; screenshot 4 in `docs/user_manual.md` (pending) |
| Easy for non-technical users | Plain-language text, no numbers without units, demo note about 2020 dates; `test_forecast_page_says_it_is_a_2020_demo`; `docs/user_manual.md` |
| Foolproof | No free text for the city (dropdown filled from `/cities`); unknown city is 404, missing is 422 (`test_forecast_unknown_city_is_404`, `test_forecast_missing_city_is_422`); ops buttons hidden until the backend accepts the key (`test_console_hides_ops_until_key_and_rejects_wrong_key`); `http://` and `:8501` redirect to HTTPS |
| Free of UI errors | Friendly messages instead of tracebacks (`test_forecast_page_friendly_message_when_backend_down`, `..._when_model_down`); every error has one JSON shape (`test_unknown_route_and_method_use_error_body`); `/forecast` and `/console` paths exist (`test_app_serves_forecast_and_console_paths`); developer toolbar hidden (`.streamlit/config.toml`, `test_streamlit_config_hides_developer_toolbar`). Browser check done (E2E-17); the one UI fault it found, the cut-off replay time (D-5), is fixed |
| Good colours, shapes, look-and-feel | CPCB colours (`src/backend/aqi.py`, `test_aqi_categories_match_hld`), readable text colour on each (`test_text_color_picks_readable_ink`), rounded cards (`src/frontend/helpers.py::card_html`). Screenshots 4 and 6 (pending) |
| Responsive | Streamlit centred layout and column flow. Checked in Firefox's responsive mode at iPhone 14 size, 393 x 852: the page fits and the two cards stack (`docs/screenshots/05_forecast_mobile.png`, E2E-17) |
| User manual exists | `docs/user_manual.md`, with 11 screenshots (`docs/screenshots/`) |

### ML Pipeline Visualization [2]

| Rubric line | Proof |
|-------------|-------|
| Separate UI screen for the pipeline, incl. ingestion and engineering | `https://localhost/console` (`src/frontend/console_page.py`): DVC DAG of all 7 stages coloured by last status, stage table with duration, rows and rows/sec; Grafana "AQ pipeline" dashboard (`monitoring/grafana/dashboards/aq_pipeline.json`). Screenshots 8, 9 (pending) |
| Pipeline management console | Console Operations section: replay start/stop/reset, retrain, rollback (`/ops/*`, `test_console_with_key_shows_drift_and_posts_retrain`); links to MLflow, Grafana, Prometheus. Screenshot 11 (pending) |
| Console of errors, failures and successful runs | Runs table with counts of successful and failed runs and the error column (`/pipeline/runs`, `test_pipeline_stages_and_runs`, `test_count_runs`); failed stage records written by `src/common/stage_runner.py` (`test_failure_is_recorded_and_wrapped`); `PipelineStageFailed` alert |
| Pipeline speed and throughput | rows/sec per stage in `reports/stage_metrics/*.json`, the console table and the Pushgateway; numbers in `docs/metrics.md` (ingest about 420,000 rows/s, validate about 100,000, features about 24,000) |

## Software Engineering [5]

### Design Principle [2]

| Rubric line | Proof |
|-------------|-------|
| Design document | `docs/HLD.md` (decisions and reasons), `docs/architecture.md` |
| OO or functional paradigm stated | `docs/HLD.md` section 3, "Programming paradigm": functional pipeline stages, OO services (`Forecaster`, `ReplayClock`, `DriftDetector`, `ModelRegistryClient`, `OpsRunner`, `BackendClient`) |
| LLD with API endpoints and I/O specs | `docs/LLD.md` (every endpoint, request and response, status codes, error body, metrics, file formats, env vars) |
| Architecture diagram | `docs/architecture.md` (Mermaid diagram plus one paragraph per block); short version in `README.md` |
| HLD diagram | `docs/HLD.md` section 2 (lifecycle diagram) |
| Strict loose coupling via configurable REST | The frontend imports nothing from the backend and knows only `BACKEND_URL` (`src/frontend/client.py`, `test_client_reads_backend_url_and_ca_from_env`); the frontend image copies only `src/frontend` and two small shared helpers (`docker/frontend/Dockerfile`); E2E-03 |

### Implementation [2]

| Rubric line | Proof |
|-------------|-------|
| Standard Python coding style | `ruff check` and `ruff format --check` pass (`pyproject.toml` rules incl. pydocstyle); `reports/ci/stage17/last_run.log` |
| Logging | `src/common/logging_setup.py`, used by every module; request log in the backend; failed stages logged with the message |
| Comprehensive exception handling | Project error types in `src/common/errors.py`; validate fails with named column, limit and count (`test_ceiling_message_names_column_limit_and_count`); backend middleware turns a crash into a generic 500 (`test_unexpected_error_becomes_500_without_details`); model and registry failures become 503 or a cached answer (`test_registry_failure_does_not_break_forecast`) |
| Design document strictly adhered to | The LLD is checked by tests: routes (`test_lld_lists_the_backend_routes`), feature columns (`test_features_match_lld_table_in_order`), metrics (`test_metrics_endpoint_lists_lld_metrics`, `test_every_lld_metric_is_on_a_dashboard`), alert rules (`test_alert_rules_match_lld`), model signature (`test_model_signature_matches_the_lld_columns`). When the design changed (drift rule, Stage 11), HLD, LLD and PLAN changed in the same commit |
| Inline code comments | Docstrings on every module and function (enforced by ruff `D` rules); comments where a choice needs explaining, e.g. `docker-compose.yml`, `src/frontend/app.py` |
| APIs follow the design doc interface spec | Same tests as above; `docs/test_report.md` TC-27 to TC-35 |
| Unit tests implemented | 359 pytest cases in 30 files, one per module (`tests/`), 359 passed, 0 failed (`reports/ci/final/junit.xml`, 2026-11-05) |

### Testing [1]

| Rubric line | Proof |
|-------------|-------|
| Test plan | `docs/test_plan.md` (scope, levels, environment, how to run) |
| List of test cases | `docs/test_plan.md` section 6: TC-01 to TC-48 (pytest) and E2E-01 to E2E-17 |
| Test report with passed and failed counts | `docs/test_report.md`: 359 run, 359 passed, 0 failed, per file; JUnit XML `reports/ci/final/junit.xml` |
| Acceptance criteria defined and met | `docs/test_plan.md` section 5 (AC-1 to AC-7); `docs/test_report.md` section 4, all 7 met with evidence |

## AIOps Implementation [10]

### Data Engineering [2]

| Rubric line | Proof |
|-------------|-------|
| Ingestion and transformation pipeline with Spark | `src/pipeline/ingest.py`, `validate.py`, `features.py`, `src/common/spark.py` (local mode, 2g driver, 8 shuffle partitions, CSV to Parquet in the first stage) |
| Throughput and speed of the pipeline | `docs/metrics.md` Stages 4-6 and 16; `reports/stage_metrics/*.json`; console stage table; Grafana "AQ pipeline". Spark vs pandas benchmark in `docs/metrics.md` |

### Source Control & CI [2]

| Rubric line | Proof |
|-------------|-------|
| CI implemented using DVC | `scripts/ci.sh --repro`: ruff, pytest, `dvc repro`, `dvc push`, `dvc status`, `dvc status -c`; `reports/ci/last_run.log` (Stage 16, every step PASS); `.pre-commit-config.yaml` |
| DVC DAG representing the CI pipeline | `dvc.yaml` (ingest → validate → features → train → evaluate → test → register), `dvc dag`; `test_dvc_dag_has_the_seven_stages_in_order`; drawn in the console |
| Git / DVC for source, data and model versioning | Git history (one commit or more per stage); `data/raw.dvc` and `dvc.lock` with a local remote (`.dvc/config`, `test_remote_is_local_path_not_cloud`); `models/candidate` is a DVC output; served models versioned in the MLflow registry with `champion` and `previous` aliases (`python -m scripts.rollback --list`) |

### Experiment Tracking [2]

| Rubric line | Proof |
|-------------|-------|
| Tracking while models are built | One MLflow run per train stage (`src/pipeline/train.py`); MLflow UI at `http://localhost:5000` |
| Metrics, parameters and artifacts tracked | 88 metrics per run (MAE and RMSE per model, horizon and city), resolved settings, `per_city_mae.csv`, `feature_importance.png`, `residuals.png`, drift baseline, package versions (`test_run_train_logs_beyond_autolog_and_saves_a_servable_model`) |
| Provisions beyond autolog | Autolog is not used. Tags: `git_commit`, `git_dirty`, `dvc_data_md5`, `features_md5`, `cutoff`, `trigger`, `pipeline_run_id`, `promotion`; drift metrics on drift-triggered runs (`drift_psi_max`, `drift_cities_exceeding`, `drift_mae_ratio_pooled`); evaluation against the champion |

### Exporter Instrumentation & Visualization [2]

| Rubric line | Proof |
|-------------|-------|
| Prometheus instrumentation | `src/backend/metrics.py`, `src/frontend/metrics.py`, `src/model_server/proxy.py`, `src/common/stage_runner.py` (Pushgateway), MLflow `--expose-prometheus` |
| Information points monitored | Request rate, latency histograms, error rate, prediction values, drift score per city and threshold, MAE ratio, model version, stage duration, rows/sec, memory and CPU (`docs/LLD.md` section 5, `test_metrics_endpoint_lists_lld_metrics`) |
| All components monitored | 9 scrape jobs: backend, model server, frontend, MLflow, Pushgateway (pipeline), node-exporter, Prometheus, Alertmanager, Grafana (`monitoring/prometheus.yml`, `test_prometheus_scrapes_every_component_every_15s`); all 9 targets up (metrics.md, Stage 14) |
| Grafana visualization in near real time | Two provisioned dashboards refreshing every 15 s (`monitoring/grafana/dashboards/`, `test_dashboards_refresh_every_15s_and_use_provisioned_source`). Screenshot 12 (pending) |

### Software Packaging [2]

| Rubric line | Proof |
|-------------|-------|
| MLflow for APIfication of the model | `mlflow models serve` of `aq-pm25@champion` behind a metrics proxy (`src/model_server/`, `docker/model_server/Dockerfile`); `/invocations` latency in `docs/metrics.md` Stage 9 |
| MLprojects for identical dev and test environments | `MLproject` with `python_env.yaml`; `test_pinned_env_matches_the_lock_file`; `mlflow run . -e main --env-manager local` gave the same numbers as the pipeline (metrics.md, Stage 7). In a fresh environment (2026-11-03, E2E-21) `mlflow run . -e main --env-manager uv --experiment-name aq-pm25` gave the same MAE and byte-identical LightGBM files (metrics.md, "Final audit fixes") |
| FastAPI for the APIs the UI needs | `src/backend/app.py`, contract in `docs/LLD.md` |
| Backend and frontend dockerized | `docker/backend/Dockerfile`, `docker/frontend/Dockerfile` (non-root, health checks) |
| Docker compose with them as two separate services | `docker-compose.yml` services `backend` and `frontend` (plus 8 more) in the `serve` profile; E2E-01 cold start |

## Viva [5]

| Rubric line | Proof |
|-------------|-------|
| Explain the project, choices, defend them | `docs/HLD.md` (decisions and trade-offs), `README.md`, and the "Viva questions I prepared" at the end of each part of `docs/PROGRESS.md` |

## Mandatory documents

| Document | File |
|----------|------|
| Architecture diagram with block explanations | `docs/architecture.md` |
| HLD with design choices and rationale | `docs/HLD.md` |
| LLD with endpoint definitions and I/O specs | `docs/LLD.md` |
| Test plan and test cases | `docs/test_plan.md` |
| User manual for non-technical users | `docs/user_manual.md`, with 11 screenshots and plain-language steps |

## Guidelines

| Guideline | Proof |
|-----------|-------|
| Every experiment reproducible via git commit + MLflow run ID | Run tags (above); `README.md` "Reproduce a result"; `docs/test_report.md` AC-6: v4 rebuilt with identical data hash, MAE and model files. Deterministic training: `test_lightgbm_training_is_repeatable` |
| EDA and documented data biases | `docs/eda.md` (9 biases with evidence), `docs/img/eda_*.png`, `reports/eda/*.csv` |
| Rollback for failed deployments | `ModelRegistryClient.rollback` (`src/pipeline/registry.py`), `scripts/rollback.py`, `POST /ops/rollback`, console button; auto-rollback in `src/ops/runner.py` when the smoke check fails (`test_failed_smoke_check_rolls_back`, fakes only); live drill in `docs/test_report.md` AC-5 |
| Automated monitoring and alerting | `monitoring/alerts.yml` (6 rules), `monitoring/alerts_test.yml` (promtool SUCCESS), Alertmanager webhook to the backend; live firing in metrics.md, Stage 14. Screenshot 13 (pending) |
| Automated retraining | Drift alert → webhook → `ops/requests/` → `src/ops/runner.py` → `dvc repro` with the new cutoff → gate → registry → hot swap; 2 min 47 s end to end, MLflow run tagged `trigger=drift_alert` (metrics.md, Stage 11) |
| Encryption and security | TLS 1.3 with a local CA (`scripts/make_certs.sh`), Caddy proxy (`docker/tls_proxy/Caddyfile`), HTTPS backend; API key in constant time on `/ops/*` (`test_ops_requires_key`, 30 cases); secrets only in `.env` (`test_secrets_come_only_from_env_file`, `test_certs_and_env_are_gitignored`); non-root containers (`test_every_container_runs_as_non_root`) |
| Docker Hub | All 5 custom images on Docker Hub, multi-arch (amd64 + arm64), tags `latest` and `0.1.0` (item 1, README "Docker images") |
| Multi-arch images (CLAUDE.md) | Every pushed image lists `linux/amd64` and `linux/arm64` in `docker buildx imagetools inspect`, and each config's `architecture` matches (item 1) |
| No cloud platforms | Local Spark, DVC remote is a local folder (`test_remote_is_local_path_not_cloud`), local MLflow (SQLite), CI is a local script, no cloud SDK in `pyproject.toml`. Docker Hub would be the one allowed exception, for publishing images only |
