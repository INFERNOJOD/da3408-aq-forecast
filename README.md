# Air Quality Forecasting with AIOps

This is my DA3408 course project. It forecasts PM2.5 for seven Indian cities (Delhi, Chennai, Lucknow, Hyderabad, Bengaluru, Jaipur, Kolkata), 1 hour and 24 hours ahead. It shows the result to ordinary users as a CPCB colour and one line of health advice.

The interesting part is what happens around the model. I replay the 2020 COVID lockdown hour by hour as if it were live traffic. The air suddenly gets much cleaner, the system notices that the data no longer looks like earlier years, retrains by itself, and swaps in the new model only if it beats the current one on the same hours. If a new model misbehaves, one button (or one command) rolls it back.

Everything runs on one 8 GB ARM64 VM with no cloud services: Spark for data, DVC for the pipeline and data versions, MLflow for tracking, the registry and serving, FastAPI and Streamlit for the app, and Prometheus, Alertmanager and Grafana for monitoring.

## For TAs

**Evidence gallery: [`docs/evidence/README.md`](docs/evidence/README.md).** It has one table with every rubric line and guideline, and next to each one the screenshot or terminal capture that shows it, with a caption. Every image has a strip on top with the time, the URL or command, and one line saying what it proves. The 11 screenshots in `docs/screenshots/` are the ones in the user manual.

## Architecture

```mermaid
flowchart LR
    user([User / operator]) -->|HTTPS| px[Caddy TLS proxy :443]
    px --> fe[Streamlit frontend<br/>Forecast + Pipeline console]
    fe -->|REST over HTTPS<br/>BACKEND_URL only| be[FastAPI backend :8000<br/>forecast, replay, drift, ops]
    be -->|/invocations| ms[MLflow model server<br/>aq-pm25@champion]
    be --> mlf[MLflow tracking + registry]
    ms -->|watches the champion alias| mlf
    be -->|retrain request file| runner[Ops runner on the host]
    runner -->|dvc repro| pipe[DVC pipeline in Spark:<br/>ingest → validate → features →<br/>train → evaluate → test → register]
    pipe --> mlf
    pipe -->|stage time, rows/sec| pgw[Pushgateway]
    prom[Prometheus] -->|scrape every 15 s| fe & be & ms & pgw & mlf
    prom --> am[Alertmanager] -->|drift alert webhook| be
    graf[Grafana] --> prom
```

The frontend knows one thing about the rest of the system: `BACKEND_URL`. Everything it shows comes from the REST API in `docs/LLD.md`. The backend does the work: it builds the feature row for the simulated "now", asks the model server for both horizons in one call, turns PM2.5 into a category, computes drift, and handles the operator actions behind an API key. Training is too heavy for the backend container, so the backend only writes a request file. A small runner on the host picks it up and runs `dvc repro` there. That way no container needs access to the Docker socket. The same pipeline is packaged as the `batch` compose profile (`docker compose --profile batch run --rm pipeline dvc repro`). The runner does not use that image, but I ran the full pipeline in it once on 2026-11-05: all 7 stages in 74 s, with the same result as on the host. The first attempt failed because the container runs as my uid, which the image does not know. The fix is in compose, `docs/test_report.md` D-4.

I split compose into two profiles because of the 8 GB limit. `serve` is always on (10 small containers, about 1.3 GiB at idle). `batch` holds Spark and training, and never runs next to the full serve stack.

The diagram with every block explained is in `docs/architecture.md`. The design choices and their reasons are in `docs/HLD.md`.

## Run it

You need Docker with Compose, [uv](https://docs.astral.sh/uv/), Java 17 (for Spark) and openssl. The DVC remote is a folder on this VM (`.dvc/config`). On another machine, copy that folder over and point DVC at it with `dvc remote modify localremote url <path>`.

**Once, on a fresh clone:**

```
scripts/bootstrap.sh
```

It writes `.env` with a random operator key, makes the certificates, installs the pinned Python environment (`uv sync --frozen`), pulls the raw data with `dvc pull`, and runs the whole pipeline once, which registers the first model as champion. In a fresh clone on this VM it took 7 min 20 s: 6 minutes to download the Python packages that were not in uv's cache, and 75 s for the pipeline itself. git and DVC hold the code and the data, but not the MLflow registry. Without this first run the model server has no model to load, and the backend never starts. The script refuses to run while the serve stack is up, because Spark and the stack do not fit in 8 GB together.

**Every time, two commands:**

```
docker compose --profile serve up -d
uv run --frozen python -m src.ops.runner
```

The first starts the app and the monitoring (10 containers). The second starts the ops runner on the host and keeps running, so start it in its own terminal or with `nohup`. The runner turns retrain requests into `dvc repro`. Without it, a drift alert still fires and a retrain request is still written to `ops/requests/`, but it stays `queued` and nothing retrains. During a retrain the runner stops the frontend and Grafana for two to three minutes, so the batch never runs next to the full stack, and starts them again afterwards. In that time the page shows "Back in a few minutes".

Open **https://localhost**. The browser warns about the certificate the first time, because I made it myself. `docs/user_manual.md` explains what that means and how to get rid of it. The console is at `https://localhost/console`, Grafana at `http://localhost:13000`, MLflow at `http://localhost:5000` and Prometheus at `http://localhost:19090`.

Other commands I use:

```
scripts/ci.sh                         # lint, 370 tests, dvc status, dvc status -c (about 1 min)
docker compose --profile serve stop
scripts/ci.sh --repro                 # + the full DVC pipeline and dvc push (about 2.5 min)
python -m scripts.replay              # drift acceptance test over 2016-2020
python -m scripts.rollback --list     # registry versions and aliases
docker compose --profile serve up -d --build   # after changing service code; plain up -d keeps the old images
mlflow run . -e main --env-manager uv --experiment-name aq-pm25   # train through MLproject in its own environment
scripts/capture_evidence_host.sh terminals   # evidence gallery: command outputs (browser part: see scripts/capture_evidence.py)
```

## What I measured

All of these were measured on the project VM (4 CPU, 7.2 GB RAM, ARM64). The full tables, with how each number was taken, are in `docs/metrics.md`.

**Pipeline (Spark, local mode, 2 GB driver).** It ingests 3,434,754 rows from 5 CSV files. Ingest takes 8 to 10 s (about 330,000 to 430,000 rows/s, CSV 283 MB to Parquet 65 MB), validate 32 to 37 s (48 checks), features 12 to 15 s and train 24 to 27 s. The whole 7-stage `dvc repro` took 97 s in the last CI run. pandas did the ingest job twice as fast as Spark (3.7 s against 8.2 s), because the data fits in memory and Spark pays for JVM start-up and job planning. I use Spark because the course requires it, and because its code keeps working when data outgrows RAM. I have not tested that second point.

**Model.** Mean absolute error in µg/m³, every model scored on the same rows:

| Model | v1, 1 h | v1, 24 h | v4 (lockdown), 1 h | v4 (lockdown), 24 h |
|-------|-----:|-----:|-----:|-----:|
| Persistence | 5.13 | 14.70 | 4.02 | 10.80 |
| Seasonal naive | 15.49 | 14.70 | 10.26 | 10.80 |
| Ridge | 5.03 | 14.25 | 4.27 | 10.55 |
| **LightGBM (served)** | **4.50** | **13.54** | **3.54** | **9.39** |

v1 was trained up to 24 March 2020. v4 is the model the system trained by itself after the drift alert, with data up to 2 April. The evaluation windows are short (497 rows at 1 h, 336 at 24 h). Per city the model is not better everywhere. On v4's window it beats the best baseline in all 7 cities at 1 h, but at 24 h it loses to it in 4 of 7 (Chennai, Lucknow, Hyderabad and Jaipur, by 0.5 to 2.1 µg/m³). It still has the lowest MAE over all cities together at 24 h, mainly because of Delhi (11.06 against 14.38). Each city has only about 48 rows at 24 h on this window, so these per-city numbers are noisy. On v1's window it lost in Kolkata and Lucknow.

**Serving.** `GET /forecast` over HTTPS takes 9.5 ms at p50 and 13.5 ms at p95 (300 serial calls). The acceptance limit was 300 ms. The model server alone takes 6.5 ms for the 14 rows the backend sends. A cold start of the stack takes 25 to 36 s with 0 restarts.

**Drift and retraining.** Replaying 25 March to 30 June of every year, the drift rule fires for 661 of 2,185 hours in 2020 and for 0 hours in 2016-2019. In the live loop it took 2 min 47 s from "drift is true" to the new model answering forecasts: the alert, the webhook, the retrain request, `dvc repro` with the new cutoff, the gate, the registry and the hot swap. The new model beat the old one on the lockdown window (mean MAE 6.467 against 6.750).

**Tests.** 370 pytest cases, 370 passed, 0 failed. `docs/test_report.md` checks the seven acceptance criteria one by one, and all seven are met.

## Reproduce a result

Every model can be traced to the code and data that made it. Each MLflow run is tagged with `git_commit`, `git_dirty`, `cutoff`, `dvc_data_md5` (the raw data version) and `features_md5` (a hash of the feature values). To rebuild a model from its run ID:

```
# 1. read the tags of the run (or open it in the MLflow UI)
python -c "import mlflow; print(mlflow.MlflowClient('sqlite:///mlflow.db').get_run('<run_id>').data.tags)"
# 2. get that code and data
git checkout <git_commit>
dvc pull
# 3. if git_dirty is true because the ops runner moved the cutoff, set the run's
#    cutoff in params.yaml (that is the only file the runner changes)
# 4. rebuild (batch profile only, so stop the serve stack first)
docker compose --profile serve stop
PIPELINE_TRIGGER=manual PIPELINE_RUN_ID="manual-$(date +%Y%m%d-%H%M%S)" dvc repro
```

`PIPELINE_RUN_ID` gives all 7 stages one run id. Without it, each stage stamps its own, and the console's pipeline diagram shows only the last stage of the run, with the other six as not run.

I checked this on the current champion. Its run `498b149f…` gives commit `b2eff79` and cutoff 2020-04-02 19:00. A clean rebuild with that cutoff gave the same data and feature hashes, the same MAE to every printed digit (6.467113514419853), and LightGBM model files that are identical byte for byte. The rebuild was at commit `92537ef`, a later commit with the same pipeline code; I did not check out `b2eff79` itself (`docs/test_report.md`, AC-6). Training is deterministic because I made it so (see below).

## What broke, and how I fixed it

These are the problems that taught me the most. The full story of each stage is in `docs/PROGRESS.md`.

**DVC said "up to date" while the remote was empty.** A broad `/data/*` rule in `.gitignore` made DVC skip `data/raw.dvc` without any error. I replaced it with the exact sub-folders. Since then I check `dvc status -c` in CI rather than trusting `dvc push`.

**LightGBM was not repeatable.** The same stage gave 14.20 and then 14.13 at 24 h with nothing changed, and single predictions differed by up to 5 µg/m³. With `deterministic` and `force_row_wise` the fits are identical, and a test checks it. Without that, "reproducible from commit + run ID" would have been a false claim.

**My data fingerprint changed on every run.** Spark puts random IDs in part-file names, and even after removing the names, 63 bytes of the Parquet footer differed between identical runs. I now hash the values themselves, sorted by city and time. A tag that is always different looks exactly like a tag that works, so I would not have noticed without comparing two runs.

**The drift rule I designed could never fire.** The plan was "3 cities above their PSI threshold and the 72 h error ratio above 1.5". I measured it before building anything around it. It fired for 13 hours in normal 2018 and never during the lockdown. The model's error grows with the PM2.5 level, and lockdown air is cleaner, so the error went *down* (ratio at most 1.47). I took the error condition out of the trigger and set the city count from normal weeks only. 4 cities required; the most seen in normal 2016–2019 weeks was 3, so the margin is one city, and it was set on those same weeks. I say so in the test report.

**MLflow kept getting killed.** At a 512 MB limit it was OOM-killed 11 times in 5 minutes, and at 1 GB it still hit the limit. The cause was 4 server workers plus a background job runner. With one worker and the job runner off, it uses about 350 MB.

**Services started before their dependencies were ready.** Plain `depends_on` only waits for a container to start. I added health checks and `condition: service_healthy`, so mlflow, model server, backend and frontend come up in order and a cold start needs no manual restart.

**The proxy made every page 40 times slower.** Through Caddy, Streamlit's health check took 42 ms instead of 0.3 ms, but only on reused connections. That pointed to a Nagle and delayed-ACK stall. Turning off keep-alive from Caddy to Streamlit brought it to 1.0 ms.

**Rollback through the app had never worked.** I found this while writing the test report. The first `POST /ops/rollback` hung, and MLflow logged "attempt to write a readonly database". I had mounted `mlflow.db` as a single file, so its folder inside the container belonged to root and SQLite could not write its journal. Reads worked, and as far as I can tell every earlier write had come from a process on the host, which is why nothing showed it. Worse, the backend kept retrying the call I had given up on, and applied that rollback about 4 minutes later. I now mount the folder, and the backend's MLflow client gives up after 2 retries and 10 s.

## Docker images

I published all five custom images to Docker Hub on 2026-11-05, each for `linux/amd64` and `linux/arm64`. `0.1.0` is the version in `pyproject.toml`, and `latest` points to the same index.

| Image | Docker Hub | Tags |
|---|---|---|
| frontend | [infernogod/aq-frontend](https://hub.docker.com/r/infernogod/aq-frontend) | `latest`, `0.1.0` |
| backend | [infernogod/aq-backend](https://hub.docker.com/r/infernogod/aq-backend) | `latest`, `0.1.0` |
| model server | [infernogod/aq-model-server](https://hub.docker.com/r/infernogod/aq-model-server) | `latest`, `0.1.0` |
| MLflow server | [infernogod/aq-mlflow](https://hub.docker.com/r/infernogod/aq-mlflow) | `latest`, `0.1.0` |
| pipeline (batch) | [infernogod/aq-pipeline](https://hub.docker.com/r/infernogod/aq-pipeline) | `latest`, `0.1.0` (also `0.1.0-amd64`, `0.1.0-arm64`, see below) |

`aq-mlflow` is a thin layer on top of the model-server image. The script builds it with `BASE=infernogod/aq-model-server:latest`, so each platform is built on the published model-server image of the same platform. I pushed it last, after the other four, and it took 4.5 min.

The VM is ARM64, so the amd64 half ran under QEMU emulation. With 7.2 to 7.9 GB of free disk, I built one image at a time and pruned the build cache in between. Build and push took 10.5 min for the frontend, 32 min for the backend and 24 min for the model server. The first backend try died after 7 minutes when the connection to PyPI broke, and the second try worked. Those three, and later `aq-mlflow`, came from `scripts/build_multiarch.sh` with `SERVICES` set to one image. The pipeline image is 2.6 GB per platform, so building both platforms at once would have needed about 5 to 7 GB of cache. That is too close to a full disk, with the serve stack writing to the same disk. So I built it one platform at a time (25.5 min for arm64, 28.4 min for amd64), pushed each under `0.1.0-arm64` and `0.1.0-amd64`, and joined them with `docker buildx imagetools create`. The default Docker builder cannot push by digest, which is why the two per-platform tags exist. During the pipeline builds, a watchdog checked the disk every 10 s and would have cancelled below 2.5 GB free. The lowest it saw was 4.97 GB.

`docker buildx imagetools inspect` for each `0.1.0` tag (trimmed to the image manifests; each image also has one provenance attestation per platform, listed as `unknown/unknown`). The `latest` tags give the same index digests. I also checked the `architecture` field in each image config: every amd64 manifest is an amd64 build and every arm64 manifest is arm64.

```
$ docker buildx imagetools inspect infernogod/aq-frontend:0.1.0
MediaType: application/vnd.oci.image.index.v1+json
Digest:    sha256:14ec891bb6046746b1a43a920d6045f8fa5e5276c99574a262e32213d7d8558e
  linux/amd64  sha256:2d6dc66f18e4a8b55acee4da5a415f9d30d00eb27f4b816566525070b5f181fd
  linux/arm64  sha256:d6d5b82cfdcfd96ae876d8c86fd2df2bf3f9af677db07a1d1e40252c84581c21
  (+ 2 attestation manifests, unknown/unknown)

$ docker buildx imagetools inspect infernogod/aq-backend:0.1.0
MediaType: application/vnd.oci.image.index.v1+json
Digest:    sha256:b5a254bd2b8684754f01a261f63029a184d105acbb62d3838663fa642d154687
  linux/amd64  sha256:0ba7b5fc2a4fa1bcac29cbe52a16f63f7bf70b9432f8fc5a00629f85a23074e5
  linux/arm64  sha256:a4e0584152bc1cc56e1d5c8994bac4a79e7f616fd6165659640ba05c670ad7f6
  (+ 2 attestation manifests, unknown/unknown)

$ docker buildx imagetools inspect infernogod/aq-model-server:0.1.0
MediaType: application/vnd.oci.image.index.v1+json
Digest:    sha256:9a701010d9d4e8c46a7d965f37c523d03d0dd29e460923224bf7e4cdbe0617eb
  linux/amd64  sha256:0844ac3846fd4400a77eb419da16f0450f7ce9ca215542450ad3c80fd0c35572
  linux/arm64  sha256:6547feaafbf04663d2e30d3b52df73c0f9d889031e55c1ec3eb308a1e3cd9d74
  (+ 2 attestation manifests, unknown/unknown)

$ docker buildx imagetools inspect infernogod/aq-mlflow:0.1.0
MediaType: application/vnd.oci.image.index.v1+json
Digest:    sha256:480341e8bcc93700a38ba59bbbce61b2dd02dc20eddf9142efe1a1ab30e85d55
  linux/amd64  sha256:27a70ad827071ca0d8d15aab2a7e068bc4967c6da8800e70d230abf5b90b755a
  linux/arm64  sha256:4980449e03c9990c9e518c003eba38e283341eb9317a4ae174ed86812c8aa31f
  (+ 2 attestation manifests, unknown/unknown)

$ docker buildx imagetools inspect infernogod/aq-pipeline:0.1.0
MediaType: application/vnd.oci.image.index.v1+json
Digest:    sha256:376209d720ec7362074fdef8e9c2fcaa2dff7c1b6116c5d714f8b8a0d2ab44b4
  linux/arm64  sha256:1ebc37267c41fa2a8f72104a6c21763d87f011bee7e42c29f56d114b50da05be
  linux/amd64  sha256:ae37ff7a2bac81b8a830b66fb67f1e39fa3becfaf9f589e81e863db62164523e
  (+ 2 attestation manifests, unknown/unknown)
```

## Where to find things

| What | Where |
|------|-------|
| Architecture, HLD, LLD (API contract) | `docs/architecture.md`, `docs/HLD.md`, `docs/LLD.md` |
| Test plan, test report | `docs/test_plan.md`, `docs/test_report.md` |
| User manual | `docs/user_manual.md` |
| Measured numbers | `docs/metrics.md` |
| EDA and data biases | `docs/eda.md` |
| Rubric checklist | `docs/rubric_checklist.md` |
| Evidence gallery (screenshots per rubric line) | `docs/evidence/README.md`, made by `scripts/capture_evidence.py` |
| Pipeline code (Spark stages, training, gate, registry) | `src/pipeline/`, `dvc.yaml`, `params.yaml`, `MLproject` |
| Backend, frontend, model server | `src/backend/`, `src/frontend/`, `src/model_server/` |
| Drift, ops runner | `src/monitoring/drift.py`, `src/ops/runner.py`, `scripts/replay.py` |
| Monitoring | `monitoring/` (Prometheus, alert rules and promtool tests, Grafana dashboards) |
| Containers | `docker/`, `docker-compose.yml`, `scripts/build_multiarch.sh`, Docker Hub ("Docker images" above) |
| CI | `scripts/ci.sh`, `.pre-commit-config.yaml`, `reports/ci/` |

## How I built this, and AI use

I used Claude Code, Anthropic's AI coding assistant, throughout this project, under my direction. I chose the problem and made the design decisions. `docs/HLD.md` records them with their reasons, and I can defend each one. Claude Code wrote code, tests and documents from my instructions. I worked one stage at a time and reviewed every stage before it was committed: I read the changes, ran the tests and the live checks, and asked for fixes where something was wrong. The rules I gave it (the fixed stack, the machine limits, the code rules and this writing voice) are in `CLAUDE.md`, and `docs/PROGRESS.md` records each stage as it was built.

The evidence gallery in `docs/evidence/` was captured automatically by `scripts/capture_evidence.py` (Playwright in Docker, with `scripts/capture_evidence_host.sh` for the terminal outputs), written by Claude Code under my direction. The 11 user-manual screenshots in `docs/screenshots/` I took myself, by hand.

Every commit carries a `Co-Authored-By: Claude …` trailer, so the git history shows that this applies to the whole project, not to selected parts.

## Not done yet

- The GitHub remote and the demo video.
- A check on a real phone. The narrow layout is checked only in Firefox's responsive mode.
