# Architecture

Everything runs locally on one ARM64 VM with Docker Compose. There are two compose profiles:
**serve** (always on) and **batch** (Spark pipeline and training, started on demand).

```mermaid
flowchart LR
    user([Non-technical user / operator])

    subgraph serve["Compose profile: serve"]
        fe["Frontend<br/>Streamlit :8501<br/>Forecast page + Pipeline console"]
        be["Backend<br/>FastAPI :8000 (HTTPS)<br/>forecast, replay, drift, ops"]
        ms["Model server<br/>mlflow models serve :5001<br/>aq-pm25@champion"]
        mlf["MLflow tracking + registry :5000<br/>SQLite + local artifacts"]
        prom["Prometheus :9090"]
        pgw["Pushgateway :9091"]
        am["Alertmanager :9093"]
        graf["Grafana :3000"]
        ne["node-exporter :9100"]
    end

    subgraph batch["Compose profile: batch"]
        pipe["Pipeline container<br/>dvc repro: ingest → validate → features →<br/>train → evaluate → test → register<br/>(Spark local, LightGBM)"]
    end

    runner["Ops runner (host process)<br/>executes retrain requests,<br/>post-deploy smoke check, auto-rollback"]
    raw[("data/raw CSV<br/>DVC-tracked, local remote")]
    feat[("data/features Parquet<br/>reports/ stage records")]
    git[("Git repo<br/>code, dvc.lock, params")]
    hub[("Docker Hub<br/>images only")]

    user -->|browser| fe
    fe -->|REST, BACKEND_URL env var| be
    be -->|REST /invocations| ms
    be -->|registry aliases, run info| mlf
    ms -->|loads model on alias change| mlf
    be -->|reads| feat
    be -->|writes retrain request| runner
    runner -->|docker compose --profile batch run| pipe
    pipe --> raw
    pipe --> feat
    pipe -->|params, metrics, artifacts, models| mlf
    pipe -->|stage duration, rows/sec| pgw
    runner -->|commit dvc.lock + params| git
    prom -->|scrape /metrics 15s| fe & be & ms & pgw & ne
    prom -->|alerts| am
    am -->|webhook /ops/alerts| be
    graf -->|queries| prom
    pipe -. images .-> hub
```

## Blocks

| Block | Responsibility | Why it exists |
|-------|----------------|---------------|
| **Frontend** (Streamlit) | Page 1, Forecast: city dropdown, PM2.5 1h/24h forecast, AQI colour card, health advice. Page 2, Pipeline console: DAG status, run history (success/fail and errors), throughput, drift, model versions, ops buttons. | The only thing users see. It knows nothing except `BACKEND_URL`, so it can be replaced or moved independently. |
| **Backend** (FastAPI) | Single REST API for the UI. Builds the feature row for a city at the simulated "now", calls the model server, converts PM2.5 to an AQI category and advice. Runs the lockdown replay clock, computes drift and rolling error, handles ops actions (API key), receives Alertmanager webhooks. | Keeps all logic out of the UI. One contract (`docs/LLD.md`) between UI and system. |
| **Model server** (MLflow) | Serves the registered pyfunc model `aq-pm25` at alias `champion` via `/invocations`. A small watcher in the container restarts serving when the alias moves (promotion or rollback). | Course requirement: "MLflow for APIfication". It separates model runtime from API logic. |
| **MLflow tracking + registry** | Stores runs (params, metrics, artifacts, git commit, data hash) and model versions with aliases `champion` and `previous`. | Experiment tracking, promotion and rollback all go through one registry. |
| **Pipeline** (batch) | The 7-stage DVC DAG. Spark handles ingest, validate and features; LightGBM, Ridge and naive baselines handle train; then the evaluation gate and registration. | DVC gives the CI DAG and data versioning; Spark is the required data-engineering engine. |
| **Ops runner** (host) | Watches `ops/requests/` for retrain requests. Pauses the frontend and Grafana, runs the batch pipeline, commits `dvc.lock`, restarts the paused services, smoke-tests the new champion, and rolls back on failure. | It stops batch and the full serve stack from running together (8 GB limit). No container gets the Docker socket. |
| **Prometheus / Pushgateway / node-exporter** | Scrape every component every 15s; the pipeline pushes stage metrics because batch jobs are short-lived; node-exporter reports host RAM and CPU. | Monitoring on all components. |
| **Alertmanager** | Routes drift and error alerts to the backend webhook. The backend logs them, and drift alerts create a retrain request. | Closes the automated loop: monitor → alert → retrain. |
| **Grafana** | Dashboards provisioned from JSON, 15s refresh. | Near-real-time visualisation. |
| **DVC local remote / Git / Docker Hub** | Data and model versions / code and pipeline lock / published multi-arch images. | Versioning and packaging. Docker Hub only stores images. |
