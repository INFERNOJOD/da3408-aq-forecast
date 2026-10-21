# Build Plan

Stages run strictly in order; each ends with a commit and a go-ahead check.
Rubric references point to `docs/rubric.md`. The coverage matrix at the end
lists every rubric line and the stage that delivers it.

| # | Status | Stage | Rubric lines satisfied | Artifact that proves it |
|---|--------|-------|------------------------|-------------------------|
| 0 | Done `1c7e4c7`, `ed76c08`, `6b50365` | Environment check, plan, quick data profile, repo hygiene, rubric | Source Control (Git) | `CLAUDE.md`, `docs/PLAN.md`, `docs/rubric.md`, `docs/data_notes.md`, `.gitignore`, git history |
| 1 | Done `36e98ec` | Design docs, written before any service code. Architecture diagram with an explanation of each block. HLD with its own diagram, design choices and rationale, and the stated paradigm: functional pipeline stages plus OO service classes (`Forecaster`, `DriftDetector`, `ModelRegistryClient`). LLD with every endpoint, request/response schema, status codes and errors. Loose-coupling rule: the frontend knows only `BACKEND_URL`. | Design Principle (all lines); mandatory docs: architecture, HLD, LLD | `docs/architecture.md` (Mermaid diagram), `docs/HLD.md` (HLD diagram), `docs/LLD.md` |
| 2 | Done `6f8ca82` | Project skeleton and tooling: uv venv, `pyproject.toml` (ruff, pytest), shared logging and exception helpers, `.env.example`, `params.yaml` | Implementation (style, logging, exceptions, comments); security (secrets in .env) | `ruff check` clean, `pytest` runs, `.env` gitignored |
| 3 | Done `1de6eed` | DVC init with a local remote; `data/raw` tracked by DVC | Source Control (data versioning) | `data/raw.dvc`, `.dvc/config`, `dvc push` log |
| 4 | Done `2491249` | Spark `ingest` stage: CSV -> Parquet (driver 2g, 8 shuffle partitions). Each stage writes a timing and rows/sec record and pushes it to Pushgateway (once Stage 14 is up; it no-ops until then). | Data Engineering (Spark, throughput, speed) | `src/pipeline/ingest.py`, `data/interim/*.parquet`, `reports/stage_metrics/*.json`, `docs/metrics.md`, tests |
| 5 | Done `040e474` | Spark `validate` stage: schema, value ranges, duplicates, missing share; fails the pipeline on hard errors | Data Engineering; Implementation (exception handling) | `reports/validation.json`, tests |
| 5b | Done `ed7b6bd` | EDA and data-bias documentation: Spark aggregates exported to small CSVs, plotted with matplotlib. Covers missingness by city and year, city coverage imbalance, seasonality, the lockdown shift, and station-placement bias. | Guidelines: EDA and documented data biases | `docs/eda.md` + `docs/img/eda_*.png` |
| 6 | Done `cea9532` | Spark `features` stage: complete hourly grid per city; PM2.5 lags (1, 2, 3, 24, 168 h); rolling mean and standard deviation; calendar features; targets t+1h and t+24h. Split driven by `cutoff`: training rows up to the cutoff with targets hidden after it, plus a serving set for the replay (2020-01-01..2020-06-30). Saves the drift baseline. Only runs after validate has passed. | Data Engineering | `data/features/*.parquet`, `reports/baseline_stats.json`, tests |
| 7 | Done `b0dbca6`, `410a0cc`, `865e661` | `train` stage: persistence, seasonal-naive, Ridge and LightGBM for 1h and 24h. Logs to MLflow beyond autolog: per-city error, git commit hash, DVC data hash, feature-importance plot, residual plot, environment file. `MLproject` with a pinned `python_env.yaml`, so dev and test run in the same environment. | Experiment Tracking (all lines); Software Packaging (MLproject); reproducibility (commit hash + run ID) | MLflow runs, `MLproject`, `python_env.yaml`, tests |
| 8 | Done (see `docs/PROGRESS.md`, Part 7) | `evaluate`, `test` and `register` stages. Register the best model per horizon (the better of Ridge and LightGBM by MAE) and promote only if it is within 1.02 x the best baseline and beats the current champion on the same window; the limit is not relaxed. The package holds a Ridge pipeline or a LightGBM booster per horizon. Models are versioned in the MLflow registry (aliases `champion`, `previous`) and `models/candidate` is a DVC output. Rollback script. | Source Control & CI (DVC DAG, model versioning); rollback | `dvc.yaml` (7 stages), `dvc dag` output in docs, `dvc repro` log, `reports/{eval,gate,register}.json`, registry listing, `scripts/rollback.py`, `src/pipeline/registry.py` |
| 9 | Done (see `docs/PROGRESS.md`, Part 8) | Model server: `mlflow models serve` for the `champion` alias (the registry uses aliases, not the old `Production` stage), behind a small metrics proxy, with a watcher that swaps to a new champion without dropping requests. Dockerfile with a non-root user. | Software Packaging (MLflow APIfication); Monitoring (model-server metrics) | `src/model_server/`, `docker/model_server/Dockerfile`, `tests/test_model_server.py`, a sample `/invocations` call and its latency in `docs/metrics.md` |
| 10 | Done (see `docs/PROGRESS.md`, Part 9) | FastAPI backend matching `docs/LLD.md`. User endpoints: `/cities`, `/forecast`, `/health`. Pipeline endpoints for the console: `/pipeline/runs`, `/pipeline/stages`. Ops endpoints behind an API key: `/ops/drift`, `/ops/retrain`, `/ops/rollback`, `/ops/replay`. Plus `/metrics`. Each forecast response includes `model_version`, `mlflow_run_id` and `git_commit`. Validated inputs, so bad input never causes a 500 error. | Software Packaging (FastAPI); Implementation (API follows LLD); security | `src/backend/`, pytest API tests, latency figures in `docs/metrics.md` |
| 11 | Done (see `docs/PROGRESS.md`, Part 10) | Drift detection and automated retraining: replay the lockdown period hour by hour as live traffic; compute PSI per city against the same-season reference and the rolling MAE ratio; drift = at least 4 of the 6 voting cities above their own PSI threshold (95th percentile of leave-one-year-out PSI, Kolkata does not vote). The MAE ratio is reported and drives a warning only. I changed this from "3 cities and pooled MAE ratio > 1.5" after measuring that the MAE condition never holds on the lockdown, with the owner's approval (see HLD); **acceptance: the replay triggers it at least once and normal weeks of earlier years do not** (passed: 661 h on the lockdown, 0 h in 2016-2019); on breach, the ops runner moves the cutoff and runs `dvc repro`; promotion stays gated. Auto-rollback if the newly promoted model fails its post-deploy smoke check. | Guidelines: automated retraining, rollback for failed deployments | `src/monitoring/drift.py`, `src/backend/drift.py`, `src/ops/runner.py`, `scripts/replay.py`, `reports/drift_thresholds.json`, `reports/drift_replay.json`, `monitoring/alerts.yml`, `monitoring/alertmanager.yml`, MLflow run tagged `trigger=drift_alert` (v4), tests |
| 12 | Done `d5f38cf`, page paths and demo note `0e2c1f9`; final screenshots still to take (see `docs/PROGRESS.md`, Parts 11 and 13) | Streamlit frontend, multi-page, REST-only, `BACKEND_URL` from an env var. **Page 1, Forecast** (non-technical users): city dropdown (no free text), 1h/24h PM2.5, a colour-coded AQI category card using CPCB colours, plain-language health advice, a friendly message when the backend is down, and a layout that works on phones. **Page 2, Pipeline console**: a DVC DAG diagram with each stage's last status, a table of successful and failed runs with error messages, stage durations and rows/sec, the drift status and the current model version, ops buttons (retrain, rollback, replay) protected by the API key, and links to MLflow, Grafana and Prometheus. | Front-end UI/UX; ML Pipeline Visualization (all lines) | `src/frontend/`, screenshots of both pages |
| 13 | Partly done: Dockerfiles, compose with profiles and `mem_limit`, multi-arch script written and `compose config` valid; the serve stack runs in compose (9 containers, healthy, forecast works end to end, memory in `docs/metrics.md`) and starts cold with no manual restarts (health-gated `depends_on`, `0e2c1f9`); pipeline image built (not run); multi-arch push and Docker Hub need the owner (see `docs/PROGRESS.md`, Parts 11 and 12) | Docker: a Dockerfile per service (frontend, backend, model server, pipeline), `docker-compose.yml` with `serve` and `batch` profiles, `mem_limit` on every container, multi-arch buildx (amd64 + arm64) pushed to Docker Hub | Software Packaging (dockerized, two separate services); Docker Hub | `docker compose --profile serve up` works, `docker buildx imagetools inspect` output, Docker Hub repo links |
| 14 | Done except the dashboard and fired-alert screenshots, which need a browser (see `docs/PROGRESS.md`, Part 14) | Monitoring. Prometheus scrapes frontend, backend, model server, Pushgateway (for the pipeline) and node-exporter. Information points: request rate, latency histograms, error rate, prediction values, drift score, model version, stage duration, rows/sec, memory. Grafana dashboards are provisioned as JSON with a 15s refresh, which counts as near real time. Alert rules cover drift (`aq_drift_detected == 1`, the combined rule from the HLD), forecast error, HTTP error rate and instance down. Alertmanager sends alerts to a backend webhook, which logs them and can trigger retraining. Retention 2-3 days. | Exporter Instrumentation & Visualization (all lines); automated monitoring and alerting | `monitoring/prometheus.yml`, `monitoring/alerts.yml`, `monitoring/alertmanager.yml`, `monitoring/grafana/dashboards/*.json` (provisioned), `monitoring/alerts_test.yml` (promtool), dashboard screenshots, screenshot of a fired alert |
| 15 | Done (see `docs/PROGRESS.md`, Part 15) | Security hardening: API key compared in constant time; TLS with a locally made CA and server certificate (`scripts/make_certs.sh`): HTTPS on the backend, and a Caddy proxy that serves the frontend on `https://localhost` and redirects plain HTTP (ports 80 and 8501) there; Prometheus and Alertmanager reach the backend over HTTPS and verify the CA; secrets only in `.env` (Alertmanager's key file is gone); every container runs as a non-root user | Guidelines: encryption/security | `scripts/make_certs.sh`, `docker/tls_proxy/Caddyfile`, compose, `tests/test_security.py`, `test_ops_requires_key` (401 without the key), curl over HTTPS in PROGRESS Part 15 |
| 16 | Done (see `docs/PROGRESS.md`, Part 16) | CI: a git pre-commit hook (ruff, ruff format, pytest, a guard against committing data, certificates or `.env`) plus `scripts/ci.sh` running ruff, pytest with JUnit XML, and with `--repro` also `dvc repro` and `dvc push`, then `dvc status` and `dvc status -c` (pipeline and DVC remote match git). `--repro` refuses to run while the serve stack is up. | Source Control & CI | `.pre-commit-config.yaml`, `scripts/ci.sh`, `tests/test_ci.py`, `reports/ci/last_run.log`, `reports/ci/junit.xml` |
| 17 | Todo | Testing docs: a test plan with numbered test cases and acceptance criteria, and a test report with passed/failed counts from the pytest JUnit XML. Acceptance criteria checked one by one. | Testing (all lines); mandatory doc: test plan | `docs/test_plan.md`, `docs/test_report.md` |
| 18 | Todo | User manual for non-technical users with screenshots, final metrics, and a reproducibility guide (how to rebuild any model from git commit + MLflow run ID) | UI/UX (user manual); mandatory doc; reproducibility | `docs/user_manual.md`, `docs/metrics.md`, `docs/reproducibility.md` |

## Rubric coverage matrix

| Rubric line | Stage(s) |
|-------------|----------|
| UI/UX: intuitive, non-technical, foolproof, error-free, look-and-feel, responsive | 12 |
| UI/UX: user manual | 18 |
| Pipeline Viz: separate screen, ingestion/engineering shown | 12 (page 2), 4-8 data |
| Pipeline Viz: management console | 10 (`/pipeline/*`, `/ops/*`), 12 |
| Pipeline Viz: errors / failures / successful runs console | 4-8 (stage records), 12 |
| Pipeline Viz: speed and throughput | 4-6 (rows/sec), 12, 14 |
| Design: design doc, paradigm stated, LLD, architecture diagram, HLD diagram | 1 |
| Design: strict loose coupling via configurable REST | 1, 12 |
| Implementation: style, logging, exceptions, comments, unit tests | 2 and every code stage |
| Implementation: design doc adhered to, APIs follow spec | 10 (API tests are checked against the LLD) |
| Testing: plan, cases, report with counts, acceptance criteria | 17 |
| Data Engineering: Spark pipeline, throughput and speed | 4, 5, 6 |
| Source Control & CI: DVC CI, DAG, source/data/model versioning | 3, 8, 16 |
| Experiment Tracking: metrics, params, artifacts, beyond autolog | 7 |
| Exporters: instrumentation, information points, all components, Grafana near real time | 14 |
| Packaging: MLflow serving | 9 |
| Packaging: MLproject for identical dev/test env | 7 |
| Packaging: FastAPI | 10 |
| Packaging: frontend and backend dockerized as two compose services | 13 |
| Viva | Plain-language explanation after every stage; design rationale in `docs/HLD.md` |
| Mandatory docs (5) | 1, 17, 18 |
| Reproducible via git hash + MLflow run ID | 7, 10, 18 |
| EDA and data biases | 5b |
| Rollback for failed deployments | 8, 11 |
| Automated monitoring and alerting | 14 |
| Automated retraining | 11 |
| Encryption/security | 2, 15 |
| Docker Hub | 13 |
| No cloud platforms | All (local Spark, local DVC remote, local MLflow) |

## Notes

- `docs/metrics.md` is filled in as we go (stages 4-6, 9, 10, 11), not at the end.
- `docs/LLD.md` is the API contract. Any later endpoint change edits it in the same commit.
- The serve and batch compose profiles are never run together (8 GB RAM limit).
- Docker Hub is used only to publish images (exception recorded in CLAUDE.md).
- The open decisions about the half-life and the first-model rule were closed in `docs/PROGRESS.md`, Part 6 and Part 7. The drift rule is built and tested in Stage 11; it is PSI-only with 4 cities (PROGRESS Part 10).
