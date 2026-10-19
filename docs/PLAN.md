# Build Plan

Stages run strictly in order; each ends with a commit and a go-ahead check.
"Rubric line" below is mapped from the requirements in CLAUDE.md. The mapping
must be re-checked against the official evaluation rubric text once it is
added to `docs/rubric.md`.

| # | Stage | Rubric lines satisfied | Artifact that proves it |
|---|-------|------------------------|-------------------------|
| 0 | Environment check, plan, quick data profile, repo hygiene | Project organisation, version control | `CLAUDE.md`, `docs/PLAN.md`, `docs/data_notes.md`, `.gitignore`, first git commit |
| 1 | Design docs (before any service code) | Design documentation: architecture diagram, HLD, LLD with endpoint I/O | `docs/architecture.md` (diagram + explanation), `docs/HLD.md`, `docs/LLD.md` |
| 2 | Project skeleton + tooling: uv venv, `pyproject.toml` (ruff, pytest), logging helper, `.env.example`, `params.yaml` | Code quality (PEP 8, logging, exceptions), secrets in .env | `ruff check` passes, `pytest` runs, `.env` gitignored |
| 3 | DVC init with local remote; `data/raw` tracked by DVC | Data versioning | `data/raw.dvc`, `.dvc/config` (local remote), `dvc push` log |
| 4 | Spark `ingest` stage: CSV -> Parquet (driver 3g, 8 shuffle partitions) | Data engineering with Spark, pipeline throughput | `src/pipeline/ingest.py`, `data/interim/*.parquet`, rows/sec in `docs/metrics.md`, unit tests |
| 5 | Spark `validate` stage: schema, ranges, duplicates, missing share; fail on hard errors | Data validation / quality checks | `reports/validation.json`, tests |
| 6 | Spark `features` stage: per-city hourly series, lags (1h, 24h, 168h), rolling means, calendar features, targets t+1h and t+24h; time split (train ≤ 2019, holdout 2020-01-01..2020-03-24, lockdown replay 2020-03-25..2020-07-01); drift baseline statistics | Feature engineering, drift baseline | `data/features/*.parquet`, `reports/baseline_stats.json`, tests |
| 7 | `train` stage: persistence, seasonal-naive, Ridge, LightGBM for 1h and 24h; MLflow logging of params, metrics, per-city error, git commit, DVC data version; `MLproject` file | Experiment tracking, baselines vs main model, reproducibility | MLflow runs in `mlruns/`, `MLproject`, tests |
| 8 | `evaluate` + `test` + `register` stages: compare with the current Production model, register and promote only if better; rollback script | Model registry, promotion gate, rollback | `dvc.yaml` with all 7 stages, `dvc repro` log, `dvc dag` output, registry screenshot, `scripts/rollback.py` |
| 9 | Model server: `mlflow models serve` for the registered model | Model serving | Running container, sample `/invocations` call in `docs/metrics.md` |
| 10 | FastAPI backend per `docs/LLD.md`: `/forecast`, `/cities`, `/health`, `/metrics`; ops endpoints `/ops/drift`, `/ops/retrain`, `/ops/rollback`, `/ops/replay` behind API key | REST API, security, AIOps actions | `src/backend/`, pytest API tests, latency figures in `docs/metrics.md` |
| 11 | Drift detection + automated retraining: replay the 2020 lockdown hour by hour as live traffic, compute PSI/KS drift + rolling error, trigger retrain via the DVC pipeline, gated promotion | Drift detection, automated retraining, simulated live traffic | `src/monitoring/drift.py`, `scripts/replay.py`, MLflow runs tagged `trigger=drift`, tests |
| 12 | Streamlit frontend: city picker, 1h/24h PM2.5 forecast, AQI category, plain-language health advice; backend URL from env var, REST only | User-facing UI, frontend/backend separation | `src/frontend/app.py`, screenshots |
| 13 | Docker: Dockerfile per service, `docker-compose.yml` with profiles `serve` / `batch`, `mem_limit` on every container, multi-arch buildx (amd64 + arm64) | Containerisation, multi-arch | `docker compose --profile serve up` works, `docker buildx imagetools inspect` output |
| 14 | Monitoring: Prometheus scraping frontend, backend, model server, Pushgateway (pipeline); Grafana dashboards as JSON; alert rules for drift and error rate; retention 2-3 days, scrape interval ≥ 15s | Monitoring and alerting on all components | `monitoring/prometheus.yml`, `monitoring/alerts.yml`, `monitoring/grafana/*.json`, dashboard screenshots, fired-alert screenshot |
| 15 | CI: local git hook / script running ruff + pytest + `dvc repro` | CI | `scripts/ci.sh` (or pre-commit config), run log |
| 16 | Testing docs | Test plan, test report | `docs/test_plan.md` (cases + acceptance criteria), `docs/test_report.md` (passed/failed counts) |
| 17 | User manual + final metrics | User documentation, measured performance | `docs/user_manual.md` with screenshots, `docs/metrics.md` complete |

## Notes

- `docs/metrics.md` is filled in progressively (stages 4, 7, 9, 10, 11), not at the end.
- `docs/LLD.md` is the API contract. Any later endpoint change edits it in the same commit.
- The serve and batch compose profiles are never run together (8 GB RAM limit).
