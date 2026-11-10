# Final Audit

I ran this audit on 2026-10-27 at commit `1cdba84`. I did not rely on `docs/PROGRESS.md` or `docs/rubric_checklist.md`. Every mark below comes from a file I read, a command I ran today, or a live call to the running stack. Where a mark rests on older evidence (a drill I could not repeat without changing the served model), I say so.

I fixed section (a) and re-audited on 2026-11-03; the results are in the next two sections.

Test counts in this file are the counts on the day of each check: 341 on 2026-10-27, 350 on 2026-11-03. The current count is 370 passed, 0 failed (2026-11-10: 6 tests for the evidence capture helpers and 2 for the D-6 gauge fix; 362 on 2026-11-05: 3 frontend tests for the replay-clock note, 5 for the rollback fix, 1 for the console layout and 3 for the console's ops messages and drift table). `docs/test_report.md` has the per-file numbers.

PASS means the evidence is there and works. WEAK means it exists but has a gap a grader could point at. FAIL means it is missing or broken.

## Status of the fixes (finished 2026-11-03)

I fixed section (a) between 2026-10-27 and 2026-11-03, one commit each. Section 1 below is still the audit as of `1cdba84`. The new marks are in "Re-audit on 2026-11-03", right after this table.

| (a) item | Status | Commit(s) / where |
|---|---|---|
| 1. Pushgateway persistence | **Done.** Volume moved to `/pushgateway`. A probe metric survived a full `down`/`up` (E2E-18). The real pipeline run (item 10) refilled the dashboard. | `cc0822a` |
| 2. Fresh clone / `scripts/bootstrap.sh` | **Done, tested in a clean clone** (E2E-20). Exit 0 in 7 min 20 s, v1 registered as champion, serve stack healthy in about 25 s, forecast 200, 9/9 targets up. `.env.example` no longer has container URLs. README and user manual give the new run steps. | `e0a7cb1` |
| 3. Ops runner documented | **Done** in HLD, the user manual and the README | `69e9b4e`, `3484879`, `e0a7cb1` |
| 4. Batch next to the full serve stack | **Done.** The runner stops the frontend and Grafana, then starts exactly those again. The TLS proxy serves a 503 "Back in a few minutes" page meanwhile (E2E-19). | `4841b2e` |
| 5. Stale architecture/HLD text | **Done** (inconsistencies 1-4, 8) | `4841b2e`, `3400783` |
| 6. `ci` trigger in LLD | **Done.** LLD lists `manual`, `drift_alert`, `ci`, `initial`. The clone test produced an `initial` run. | `fd7d292` |
| 7. Failures visible in the console | **Done, live since 2026-11-03.** The console has a "Failed runs" table. The labelled failure `demo-failure-20261027` (validate, PM2.5 ceiling lowered to 500, 4 hard checks failed) shows in it. Until 2026-11-03 the running frontend image did not have this code (see the re-audit). | `e10f521`; record in `reports/runs.jsonl` |
| 8. Console replay-time box | **Done, live since 2026-11-03** ("25 Mar, 00:00") | `e10f521` |
| 9. Small doc fixes (inconsistencies 9-12) | **Done.** The OpenAPI part went live on 2026-11-03 with the rebuilt backend image. | `3400783`, `56779b3` |
| 10. Real `dvc repro` | **Done.** `dvc repro -f`, all 7 stages ran in 75.5 s. The candidate tied v4 at 6.467 and was rejected. All 7 stage statuses are 1 in the Pushgateway, and `PipelineStageFailed` is inactive. | `0a81f6e` |
| Extra: MLproject in a fresh environment | **Done after a fix** (E2E-21). The first run crashed after training: `mlflow run` creates its run in the Default experiment, and `train.py` sets `aq-pm25`. With `--experiment-name aq-pm25` the run gives the same MAE and byte-identical LightGBM files as the pipeline. The command is documented with the flag. | `e10bbaf` |
| Extra: OpenAPI error responses (inconsistency 11) | **Done** | `56779b3` |
| Re-audit, `test_report.md`, README test count, final CI | **Done** (below). `scripts/ci.sh`: 350 tests, 0 failed on 2026-11-03; 362 passed, 0 failed since 2026-11-05. | `c8201f8`, `a9610f2` |

## Re-audit on 2026-11-03

I checked each line that a fix touched again, on the live stack or from a file, at `e10bbaf` and later. The other PASS lines rest on the 2026-10-27 audit. Since `1cdba84` the code changes are the runner, the console, the OpenAPI error docs, the Caddyfile, compose (the Pushgateway volume) and the bootstrap script. None of them touches what those lines depend on.

### A new finding: the running images were stale

The backend and frontend images were built on 2026-10-21. Compose copies the code into the image and mounts no `src/`, and `docker compose up -d` does not rebuild an image that already exists. So the 2026-10-27 fixes to the console and the OpenAPI spec were committed and unit-tested, but the live stack did not run them. I noticed this because the live `/openapi.json` still listed only 200, 202 and 422. I rebuilt both images (`docker compose --profile serve build backend frontend`, 4 min 55 s, because the pip layer was no longer in the build cache) and restarted the two services. After that the spec listed 400, 401, 404, 409, 500 and 503. Rendered with Streamlit's `AppTest` against the live backend, the console showed "18 successful, 2 failed (last 20)", the "Failed runs" table and "Replay time 25 Mar, 00:00". The README now gives `up -d --build` for after a code change. The clone test (E2E-20) also ran on the old images. That does not change its result, because what it tested (`.env`, data, first model, health checks, forecast) does not depend on the console or the OpenAPI text.

### Marks that changed

| Rubric item | Was | Now | Evidence today |
|---|---|---|---|
| Free of UI errors | WEAK | PASS | Replay time no longer cut off ("25 Mar, 00:00" live), Deploy button hidden in the running image. Not yet seen in a real browser (E2E-17, (b)1) |
| Console of errors, failures, successful runs | WEAK | PASS | Live console: 18 successful, 2 failed in the last 20, "Failed runs" table with `demo-failure-20261027` and the real MLproject crash `20261103-173537` |
| Pipeline speed and throughput | WEAK | PASS | Every query in the "AQ pipeline" dashboard returns data (7 stage durations, 6 throughputs; `test` reports no rows/s). Fresh run: ingest 442,395 rows/s |
| Architecture diagram | WEAK | PASS | `architecture.md`: the runner runs the pipeline "on the host", stops and restarts frontend and Grafana, no commit arrow |
| Design document strictly adhered to | WEAK | PASS | `ci` is in the LLD trigger list; the runner pauses the frontend and Grafana as HLD says; all 14 routes match the LLD both ways (live spec) |
| Grafana in near real time | WEAK | PASS | Pipeline dashboard has data, 15 s refresh |
| MLproject for identical environments | WEAK | PASS | E2E-21, fresh environment, same MAE and identical model files |
| Architecture diagram with block explanations (mandatory doc) | WEAK | PASS | as above |
| Automated retraining | WEAK | PASS | The runner is documented as the second start command (README, user manual, HLD). Pause and resume checked live (E2E-19), the full drift-to-new-model loop in E2E-07. Caveat: the full loop has not been run again since the pause was added, and the runner is not running right now |

Unchanged:

- Responsive: WEAK
- User manual exists: WEAK
- User manual (mandatory doc): WEAK
- Docker Hub: FAIL
- Multi-arch images: FAIL

All five need me (section (b)).

**Tally:** 60 lines. On 2026-10-27: 46 PASS, 12 WEAK, 2 FAIL. Now: 55 PASS, 3 WEAK, 2 FAIL. Every line still open is in section (b).

### Update on 2026-11-05: Docker Hub and multi-arch images

| Rubric item | Was | Now | Evidence |
|---|---|---|---|
| Docker Hub | FAIL | PASS | All five custom images pushed: [aq-frontend](https://hub.docker.com/r/infernogod/aq-frontend), [aq-backend](https://hub.docker.com/r/infernogod/aq-backend), [aq-model-server](https://hub.docker.com/r/infernogod/aq-model-server), [aq-mlflow](https://hub.docker.com/r/infernogod/aq-mlflow), [aq-pipeline](https://hub.docker.com/r/infernogod/aq-pipeline), tags `latest` and `0.1.0`. It was WEAK for a few hours, until I pushed `aq-mlflow` the same day |
| Multi-arch images | FAIL | PASS | Every pushed index lists `linux/amd64` and `linux/arm64`, and each config's `architecture` field matches its platform |

Index digests and platforms from `docker buildx imagetools inspect <image>:0.1.0` (2026-11-05; `latest` gives the same digests):

| Image | Index digest | Platforms |
|---|---|---|
| `infernogod/aq-frontend` | `sha256:14ec891bb604…` | linux/amd64, linux/arm64 |
| `infernogod/aq-backend` | `sha256:b5a254bd2b86…` | linux/amd64, linux/arm64 |
| `infernogod/aq-model-server` | `sha256:9a701010d9d4…` | linux/amd64, linux/arm64 |
| `infernogod/aq-mlflow` | `sha256:480341e8bcc9…` | linux/amd64, linux/arm64 |
| `infernogod/aq-pipeline` | `sha256:376209d720ec…` | linux/amd64, linux/arm64 |

The full trimmed inspect output and how I built the images (one at a time on a small disk, the pipeline one platform at a time) are in the README, "Docker images".

**Tally after this update:** 57 PASS, 3 WEAK, 0 FAIL. The three WEAK lines are Responsive, User manual exists and User manual (mandatory doc). All three wait on the browser check and the screenshots, which are section (b)1.

### Update on 2026-11-05: screenshots and browser check

The 11 screenshots are in `docs/screenshots/`. Every image link in `docs/user_manual.md` resolves to a PNG (3420 x 2214), and I looked at them. The API key field is masked wherever it shows, and the terminal shot shows only `docker compose ps`.

| Rubric item | Was | Now | Evidence |
|---|---|---|---|
| Responsive | WEAK | PASS | `05_forecast_mobile.png`: Firefox responsive mode at iPhone 14 size (393 x 852). The page fits the width, the text wraps and the two cards stack (E2E-17) |
| User manual exists | WEAK | PASS | `docs/user_manual.md` with 11 screenshots |
| User manual (mandatory doc) | WEAK | PASS | same |
| Free of UI errors | PASS | PASS, after a fix | The browser check contradicted the 2026-11-03 evidence. The first screenshot 08 showed "Replay time" cut off as "25 Mar, …" at 90% zoom, because `AppTest` sees values and not widths. Fixed the same day: two status boxes per row, with a test, checked on the rebuilt frontend (test report D-5). Verified in a real browser: the retaken screenshot 08 shows "25 Mar, 00:00" in full |

**Tally after this update:** 60 PASS, 0 WEAK, 0 FAIL. What is left in section (b): the GitHub remote, the demo video and viva preparation, and a check on a real phone (optional).

### Other checks I ran today

- 300 serial forecasts over HTTPS on a reused connection: p50 7.5 ms, p95 10.7 ms, all 200.
- Errors: `/forecast?city=Pune` 404, missing `city` 422, `limit=0` 422, an unknown route 404, `/ops/drift` with a wrong key 401.
- 9/9 Prometheus targets up. All 6 alert rules loaded and inactive.
- The 10 serve containers used 1,298 MiB.
- `scripts/ci.sh`: ruff and format pass, 350 of 350 tests, `dvc status` and `dvc status -c` clean.

### What I left on the machine

- `.env` has `PUSHGATEWAY_URL=http://localhost:19091`, so host pipeline runs push their metrics.
- `ops/requests/rt-20261027-audit.json` is the refused request from the runner check (status `failed`).
- MLflow's Default experiment holds the crashed MLproject run (FAILED). The `aq-pm25` experiment has two new rejected candidates: `94dc83e2` from `dvc repro -f` and `de1388b9` from `mlflow run`. The registry is unchanged: champion 4, previous 1.
- The serve stack is running. The ops runner is not.
- The a4 monitoring stack from another course project (`a4-prometheus`, `a4-grafana`, `a4-alertmanager`, about 700 MB) started at 17:20 and was running the whole time I worked. I left it alone.

## What's left (as found on 2026-10-27, before the fixes)

### (a) Things I can fix

1. **Pushgateway persistence is broken.** The container runs as `nobody` (65534), but its `/data` volume is owned by root. `touch /data/probe` inside the container gives "Permission denied", and `/data` has no `pushgateway.db`. After today's restart the Pushgateway holds 0 groups, Prometheus has 0 `aq_stage_*` series, and the "AQ pipeline" Grafana dashboard is empty. Fix the volume ownership (or the user), re-push with `python -m scripts.push_stage_metrics --url http://localhost:19091`, and correct the Stage 14 sentence in `docs/metrics.md` that says the records survived a restart.
2. **The README "Run it" steps do not work from a fresh clone.** In a clean clone I found no `mlflow.db`, `mlruns/`, `data/features/`, `data/raw/` or `models/candidate/`. The README goes straight from `.env` and certificates to `docker compose --profile serve up -d`. With no registry the model server has no champion, `/ping` answers 503, the model server never becomes healthy, and `backend` (which `depends_on` it being healthy) never starts. I worked this out from the compose file and `proxy.py`; I did not start a second stack. The missing steps are `uv sync --frozen`, `dvc pull`, one first `dvc repro` to create the registry and v1, and the command that starts the ops runner. The DVC remote is an absolute path on this VM (`/home/krish-yadav/DA3408/dvc-remote`), which I should mention too.
3. **The ops runner is not documented as something to start, and it was not running.** Automatic retraining needs `python -m src.ops.runner` on the host. Neither the README nor the user manual says how to start it, and `pgrep` found no runner today. Without it, a drift alert only leaves a queued request file. The user manual tells the operator that "the system starts a retrain by itself".
4. **The batch runs next to the full serve stack.** `CLAUDE.md` and HLD say this never happens. The ops runner only checks for 2,500 MB of free memory (`src/ops/runner.py:236-241`). It then runs `dvc repro` with all 10 serve containers up, which is what happened in E2E-07. Either make the runner stop the frontend and Grafana, as HLD §5 describes, or change the docs to say what really happens.
5. **Fix the stale and contradictory text in `architecture.md` and `HLD.md`** (inconsistencies 1-4 and 8 below).
6. **Add `ci` to the `trigger` values in LLD §2 `/pipeline/runs`.** The live endpoint returns `"trigger": "ci"`, and `reports/runs.jsonl` has 7 such records. LLD allows only `manual | drift_alert | initial`.
7. **Make failures visible in the console.** `runs.jsonl` has one failed stage record ever (`20261020-141854`, validate, `KeyError: 'NO'`, a code crash rather than a data check). It is older than the last 20 runs, so the console shows "20 successful, 0 failed". For the rubric's "console of errors, failures" I need a recent, deliberate failure, for example a validation failure on a bad row, or a control to show more runs.
8. **Console layout.** The "Replay time" status box is cut off ("25 Mar 2…") at the default width (visible in the existing console screenshot).
9. **Small doc fixes:** inconsistencies 9-12 below.
10. **Optional: a real `dvc repro` for fresh evidence.** Today's `scripts/ci.sh --repro` passed, but every stage was cached (`dvc-repro PASS 0s`), so no stage actually ran. The last full execution is the 2026-10-21 CI run (97 s, `reports/ci/stage16/repro_run.log`). `dvc repro -f` would re-run everything, but it would also log one more rejected candidate in MLflow.

### (b) Things only I can do

1. **Screenshots.** *Done on 2026-11-05, see "Update on 2026-11-05: screenshots and browser check" above.* As of the audit: `docs/user_manual.md` has 13 `[SCREENSHOT n]` placeholders and none are filled. `docs/screenshots/` is untracked and holds two files from 2026-10-20. They predate commit `4d39d3a`, so they still show the "Deploy" button, and their names do not match the names the manual asks for (`04_forecast.png`, `08_console_top.png`, ...). Also needed: a narrow-window screenshot (responsiveness, E2E-17), Grafana during a replay, and `PM25DriftHigh` firing in Prometheus.
2. **Docker Hub and multi-arch images.** *Done on 2026-11-05 for all five images, see "Update on 2026-11-05" above.* As of the audit: none are pushed. The local images (`aq-backend`, `aq-frontend`, `aq-model-server`, `aq-mlflow`, `aq-pipeline`) are arm64 only. The only buildx builder supports `linux/arm64`, no QEMU binfmt handler is registered, and Docker is not logged in. I need to log in, install QEMU (needs sudo), run `scripts/build_multiarch.sh`, and add the image names to the README.
3. **GitHub.** The repo has no git remote at all (`git remote` prints nothing). Create the repository and push.
4. **Demo video and viva preparation.**
5. **Optional:** open the app on a real phone (the manual says this has not been done).

## 1. Rubric, line by line

### Demonstration [5]

| Rubric item | Mark | Evidence |
|---|---|---|
| UI intuitive, easy for non-technical users | PASS | Forecast page: city dropdown, one colour card per horizon, advice text (`src/frontend/forecast_page.py`; existing screenshot of Delhi) |
| Foolproof | PASS | Dropdown only (no free text); `GET /forecast?city=Pune` → 404 `UNKNOWN_CITY` today; friendly messages when the backend or model is down (TC-42, `test_forecast_page_*`) |
| Free of UI errors | WEAK | "Replay time" value cut off in the console; old screenshots show the Deploy button (now hidden by `.streamlit/config.toml`) |
| Colours, look and feel | PASS | CPCB colours from `/aqi/categories` (checked today), readable text colour per card (TC-41) |
| Responsive | WEAK | Streamlit columns stack, but nobody has checked it in a narrow browser window (E2E-17 pending) |
| User manual exists | WEAK | `docs/user_manual.md` is complete in text, but all 13 screenshots are placeholders |
| Separate UI screen for the ML pipeline | PASS | `/console` page, Graphviz DAG coloured by status; `https://localhost/forecast` → 200 today; existing console screenshot |
| MLOps tool UIs | PASS | Console links to MLflow, Grafana, Prometheus; all three answered today (Grafana `database ok`, 2 dashboards provisioned) |
| Pipeline management console | PASS | Replay, retrain and rollback behind the key; all `/ops/*` checked live today (401 without or with a wrong key, 200/400/409/422 with it) |
| Console of errors, failures, successful runs | WEAK | Runs table and counts exist, but the only failure ever recorded is outside the last 20 runs, so the console shows 0 failed |
| Pipeline speed and throughput | WEAK | Console stage table shows duration and rows/s from `/pipeline/stages` (ingest 331,188 rows/s today). The Grafana pipeline dashboard is empty right now (Pushgateway defect) |

### Software Engineering [5]

| Rubric item | Mark | Evidence |
|---|---|---|
| Design document | PASS | `docs/HLD.md` with reasons and trade-offs |
| OO or functional paradigm stated | PASS | HLD §3 "Programming paradigm"; the named classes exist (`Forecaster`, `DriftDetector`, `OpsRunner`, `BackendClient`, ...) |
| LLD with endpoints and I/O | PASS | `docs/LLD.md` §2-3. All 14 method+path pairs in the live OpenAPI spec match the LLD headings in both directions. Body limits match (`speed_hps` 0.1-20, `reason` 1-200, `limit` 1-100) |
| Architecture diagram | WEAK | `docs/architecture.md` has the diagram and block explanations, but two arrows contradict the text (inconsistency 1) |
| HLD diagram | PASS | HLD §2 lifecycle diagram |
| Strict loose coupling | PASS | `src/frontend` imports nothing from `src/backend` or `src/pipeline` (grep); only `BACKEND_URL`; inside the frontend container the client reached `https://backend:8000` with the CA |
| Python style | PASS | `ruff check` and `ruff format --check` pass (CI today) |
| Logging | PASS | `logging` via `src/common/logging_setup.py`, 62 log calls in `src/` |
| Exception handling | PASS | Custom error types, LLD error body on every non-2xx (404, 405, 422, 401, 400, 409 seen live today), catch-all 500 in the middleware |
| Design document strictly adhered to | WEAK | `trigger: "ci"` is outside the LLD enum; the runner runs the batch next to the full serve stack, against HLD |
| Inline comments | PASS | Docstrings on every module and function (ruff `D` rules), comments in compose and scripts |
| APIs follow the interface spec | PASS | Route match above; response shapes checked live for every public and ops endpoint |
| Unit tests | PASS | 341 tests, one file per module |
| Test plan | PASS | `docs/test_plan.md` |
| List of test cases | PASS | TC-01 to TC-48 and E2E-01 to E2E-17 |
| Test report with pass/fail counts | PASS | `docs/test_report.md` 341/341. I reproduced it today: `tests="341" failures="0" errors="0" skipped="0"`. The per-file counts match the report |
| Acceptance criteria defined and met | PASS | 7/7 in the report. Re-checked today: AC-2 (p95 11.5 ms), AC-3 (`drift_replay.json`), AC-7 (CI). AC-1, AC-4, AC-6 from `reports/*.json` and MLflow tags today. AC-5 from the 2026-10-21 drill (today I checked only the error paths) |

### AIOps Implementation [10]

| Rubric item | Mark | Evidence |
|---|---|---|
| Ingestion/transformation with Spark | PASS | `src/pipeline/ingest.py`, `validate.py`, `features.py`, local Spark, CSV → Parquet |
| Throughput and speed | PASS | `reports/stage_metrics/*.json`: ingest 10.4 s / 331,188 rows/s, validate 37.0 s, features 15.1 s, train 27.1 s; `docs/metrics.md` |
| CI with DVC | PASS | `scripts/ci.sh --repro` today: every step PASS, exit 0, 50 s (stages cached, see (a)10) |
| DVC DAG as the CI pipeline | PASS | `dvc.yaml`, 7 stages; `dvc dag` prints them in order |
| Git and DVC for code, data, models | PASS | `data/raw.dvc`; `dvc status -c` "Cache and remote 'localremote' are in sync". No git remote (see (b)3) |
| Tracking while models are built | PASS | MLflow experiment `aq-pm25`, 10 runs |
| Metrics, parameters, artifacts | PASS | v4 run `498b149f`: 94 metrics, 24 params, 6 artifacts (plots, per-city CSV, drift baseline, env pins) |
| Beyond autolog | PASS | Tags `git_commit`, `git_dirty`, `dvc_data_md5`, `features_md5`, `cutoff`, `trigger`; 28 per-city MAE metrics; `drift_cities_exceeding`, `drift_psi_max`, `drift_mae_ratio_pooled` |
| Prometheus instrumentation | PASS | Custom metrics in backend, model server, frontend and pipeline (LLD §5) |
| Information points monitored | PASS | Request rate, latency, errors, forecasts, drift PSI and thresholds, MAE ratios, model version, memory, CPU |
| All components monitored | PASS | 9/9 targets `up` today, before and after the restart, all at 15 s |
| Grafana in near real time | WEAK | Both dashboards refresh every 15 s and the service dashboard has data; the pipeline dashboard has no data today (Pushgateway defect) |
| MLflow for model APIfication | PASS | Model server `/invocations`; 722+ predictions counted at 1 h in Prometheus today |
| MLproject for identical environments | WEAK | `MLproject` + `python_env.yaml` pinned to `uv.lock` (TC-14). Only ever run with `--env-manager local`, never in a fresh environment |
| FastAPI for the UI's APIs | PASS | `src/backend/app.py` |
| Backend and frontend dockerized | PASS | `docker/backend/Dockerfile`, `docker/frontend/Dockerfile` |
| Compose with two separate services | PASS | `frontend` and `backend` services in `docker-compose.yml`, each with `mem_limit` |

### Viva [5]

Not something a file can show. Only I can prepare it.

### Mandatory documents

| Document | Mark | Evidence |
|---|---|---|
| Architecture diagram with block explanations | WEAK | `docs/architecture.md`; diagram contradicts text (inconsistency 1) |
| HLD with design choices and rationale | PASS | `docs/HLD.md` (stale passages listed below) |
| LLD with endpoints and I/O | PASS | `docs/LLD.md`, matches the code |
| Test plan and test cases | PASS | `docs/test_plan.md` |
| User manual for non-technical users | WEAK | `docs/user_manual.md`, no screenshots yet |

### Guideline requirements

| Requirement | Mark | Evidence |
|---|---|---|
| Reproducible via commit + MLflow run ID | PASS | Run `498b149f` tags give commit `b2eff79`, cutoff, data and feature hashes; the rebuild `c9933e83` has the same hashes and MAE (checked in MLflow today); test report AC-6. The README steps for a fresh machine are incomplete (item (a)2) |
| EDA and documented data biases | PASS | `docs/eda.md` §4, 6 figures in `docs/img/` |
| Rollback for failed deployments | PASS | `POST /ops/rollback`, `scripts/rollback.py`, smoke-check rollback in the runner. Live drill 2026-10-21 (test report AC-5). Today: 400 for version 99; registry `champion`=4, `previous`=1 |
| Automated monitoring and alerting | PASS | 6 rules loaded and inactive at rest, Alertmanager ready, `promtool test rules` SUCCESS today |
| Automated retraining | WEAK | Proven once (E2E-07, Stage 11, 2 min 47 s). Today drift went true live at sim time 2020-04-01 12:00 (4 cities). But the loop needs the host ops runner, which nothing starts and no run instruction mentions, and it was not running |
| Encryption / security | PASS | HTTPS backend and proxy; `curl` without the CA exits 60; `http://localhost/` and `:8501` → 301 to https; API key compared in constant time; no container runs as root (checked `docker inspect` today); `.env` mode 600 |
| Docker Hub | FAIL | Nothing pushed, not logged in |
| Multi-arch images (CLAUDE.md) | FAIL | Local images arm64 only; no amd64 builder or QEMU |
| No cloud platforms | PASS | No cloud SDKs or URLs in `src/`, `scripts/`, `docker/`, `pyproject.toml`; DVC remote is a local path |
| Memory limits (CLAUDE.md) | PASS | Every service has `mem_limit`; 1.23 GiB in total for the 10 serve containers today; Prometheus retention `2d`, scrape 15 s; Spark 2g driver |

## 2. Inconsistencies found

1. **`architecture.md` diagram vs its own text.** The arrow `runner -->|dvc repro on the host| pipe` points at the "Pipeline container" box in the batch profile, but the text says the runner runs `dvc repro` on the host and never starts the container. The arrow `runner -->|commit dvc.lock + params| git` contradicts "The runner does not commit `dvc.lock`".
2. **`architecture.md` (Ops runner) and HLD §3 "Memory":** "The plan is to pause the frontend and Grafana during the batch once the compose stack exists (Stage 13)" and "comes with Stage 13". The compose stack exists and the runner does not pause anything. It refuses below 2,500 MB free with the message "stop the frontend and Grafana first".
3. **HLD §5** still says "These are planned memory limits. I will measure real usage in Stage 13". The measurements exist (`docs/metrics.md`; 1.23 GiB today).
4. **HLD and `CLAUDE.md` say batch and the full serve stack never run together.** The ops runner runs `dvc repro` with the whole serve stack up (item (a)4). `scripts/ci.sh --repro` does enforce the rule, so the two paths disagree.
5. **LLD §2 `/pipeline/runs`:** `trigger` ∈ `manual | drift_alert | initial`, but the code writes and returns `ci`.
6. **`docs/metrics.md` Stage 14:** "The Pushgateway's 7 stage records were still there after the restart (persistence file in its volume)." Today the volume is not writable and holds no file. Either a later change broke it or the earlier check was lucky (a `restart` rather than a `down`). In any case the sentence is not true of the current setup.
7. **`docs/user_manual.md` §4 Drift:** "When drift is detected, the system starts a retrain by itself." That is only true if someone started the ops runner, and no document tells the operator to.
8. **HLD §3 "Promotion rule":** "'Best model' means the better of Ridge and LightGBM, as you confirmed." It speaks to a reader who confirmed something, which breaks the first-person voice.
9. **README "Model" paragraph:** "the model still loses to a baseline in Kolkata and Lucknow" comes right after the v4 sentence, but the evidence (test report AC-1, metrics.md Stage 7) is for v1's window. I found no per-city check for v4 in the docs.
10. **Numbers quoted but not in `metrics.md`.** CLAUDE.md asks for measured numbers there, but these appear only in `PROGRESS.md`: MLflow "OOM-killed 11 times in 5 minutes" (README) and "about 11 s per horizon" (HLD).
11. **OpenAPI vs LLD error contract.** `/openapi.json` lists only 200/202 and FastAPI's default 422 schema. It does not show the custom `{"error": {...}}` body or the 401, 404, 409 and 503 responses. The code follows LLD; only the generated spec is incomplete.
12. **LLD §3 `/ops/rollback`** does not say that `version` is limited to 1-20 characters, as the code enforces.
13. **Screenshots.** The test report lists E2E-17 as pending and the manual has placeholders, while `docs/screenshots/` holds two untracked, outdated files.

What I checked and found consistent:

- the 14 routes and their bodies
- the error codes on the live stack
- the v1 and v4 MAE tables (`reports/train_metrics.json`, `eval.json`, MLflow)
- `gate.json` and `register.json` (tie at 6.467, rejected)
- the drift numbers (661 h, 5 episodes, first 2020-03-31 23:00, at most 3 cities in 2016-2019)
- the thresholds (2.03 Delhi to 5.20 Chennai)
- the stage times quoted in the README
- 48 validation checks
- 3,434,754 ingested rows
- 341 tests and the per-file counts
- cold start: 30 s today, inside the quoted 25-36 s, 0 restarts
- latency: p50 8.4 ms and p95 11.5 ms today, against the reported 9.5 and 13.5 ms

## 3. What I ran today

**Smoke test on the running serve stack.**

- Every public endpoint returned 200 with the LLD shape.
- Bad requests returned the LLD error body: `/forecast?city=Pune` 404, missing `city` 422, `limit=0` 422, an unknown route 404, `DELETE /cities` 405.
- `/ops/drift`, `/ops/replay`, `/ops/retrain` and `/ops/rollback` returned 401 with no key and with a wrong key.
- With the key: a bad replay body gave 422, a second `start` gave 409, rollback to version 99 gave 400, and an empty alert payload gave 200.
- I ran the replay at 20 h/s for about 9 s. Drift went true with 4 cities over threshold at 2020-04-01 12:00, and I reset the clock before the 1-minute alert window, so no retrain request was created.
- Plain HTTP on ports 80 and 8501 redirected to https, `https://localhost/forecast` returned 200, and a call without the CA was refused (exit 60).

**Prometheus and Grafana.**

- Prometheus: 9/9 targets up, 6 rules loaded, retention 2d.
- Grafana: healthy, `aq-service` (28 panels) and `aq-pipeline` (13 panels), both refreshing every 15 s.

**CI.** I stopped the stack, then ran `CI_OUT_DIR=<scratchpad> scripts/ci.sh --repro`. Exit 0, 341 passed, `dvc repro` had nothing to do, the DVC remote is in sync. I sent the logs to the scratchpad so the tracked `reports/ci/` evidence stayed as committed.

**Restart.** `docker compose --profile serve down`, then `up -d`. The page and a forecast answered after 30 s, 0 restarts, 9/9 targets up. Then I measured 300 serial forecasts: p95 11.5 ms, all 200.

**Hygiene.**

- I scanned all 42 commits for paths like `.env`, `certs/`, keys, raw or processed data, `mlflow.db`, `mlruns/` and model files: none found. The only CSVs are the small `reports/eda/` aggregates, which are meant to be there.
- I also searched every commit for the actual values of `OPS_API_KEY` and `GRAFANA_ADMIN_PASSWORD`: no hits.
- No blob is larger than 500 KB.
- `git status` is not clean: `docs/screenshots/` is untracked.
- A fresh clone lacks everything the stack needs at runtime (item (a)2).

The memory rule held throughout: the batch ran only with the serve stack stopped. Three containers from another project (`a4-prometheus`, `a4-grafana`, `a4-alertmanager`) were running on the VM the whole time. I left them alone, but they use memory that the 2,500 MB runner check counts against.
