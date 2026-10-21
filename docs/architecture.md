# Architecture

Everything runs locally on one ARM64 VM under Docker Compose. I split the stack into two compose profiles. **serve** is always on. **batch** holds the Spark pipeline and training, and I start it only when needed.

```mermaid
flowchart LR
    user([Non-technical user / operator])

    subgraph serve["Compose profile: serve"]
        px["TLS proxy<br/>Caddy :443 (HTTPS)<br/>:80 and :8501 redirect"]
        fe["Frontend<br/>Streamlit :8501 (internal)<br/>Forecast page + Pipeline console"]
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

    user -->|browser, HTTPS| px
    px --> fe
    fe -->|REST over HTTPS, BACKEND_URL env var| be
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
    am -->|webhook /ops/alerts, HTTPS| be
    graf -->|queries| prom
    pipe -. images .-> hub
```

## The blocks

**TLS proxy (Caddy).** Browsers reach the system only through this small proxy. It holds the certificate, ends TLS on port 443 and passes requests and Streamlit's websocket to the frontend. Plain `http://` on port 80, and the old address on port 8501, get a redirect to `https://` instead of a broken page. I added it because Streamlit's own TLS option cannot answer plain HTTP on the same port, so a user who typed the old address would see an empty error page.

**Frontend (Streamlit).** It has two pages. The Forecast page is for ordinary users: a city dropdown, the 1h and 24h PM2.5 forecast, an AQI colour card and health advice. The Pipeline console is for the operator: DAG status, run history with failures and error messages, throughput, drift, model versions and the ops buttons. I kept the frontend ignorant of everything except `BACKEND_URL`. That way I can replace it or move it without touching the rest.

**Backend (FastAPI).** This is the single REST API the UI talks to. It builds the feature row for a city at the simulated "now", calls the model server, and turns PM2.5 into an AQI category with advice. It also runs the lockdown replay clock, computes drift and rolling error, handles the ops actions behind the API key, and receives Alertmanager webhooks. I put all the logic here so the UI stays thin, and so `docs/LLD.md` is the one contract between the UI and the system.

**Model server (MLflow).** It serves the registered pyfunc model `aq-pm25` at the alias `champion` through `/invocations`. A small watcher inside the container starts the new version next to the old one when the alias moves (promotion or rollback), then switches over, so no request fails. A thin proxy in front of `mlflow models serve` provides the Prometheus metrics. The course asks for MLflow to expose the model as an API, and this also keeps the model runtime separate from the API logic.

**MLflow tracking and registry.** It stores runs (parameters, metrics, artifacts, git commit, data hash) and model versions with the aliases `champion` and `previous`. Tracking, promotion and rollback all go through this one registry.

**Pipeline (batch).** This is the 7-stage DVC DAG. Spark handles ingest, validate and features. LightGBM, Ridge and the naive baselines handle train, followed by the evaluation gate and registration. DVC gives me the CI DAG and the data versioning, and Spark is the engine the course requires for data engineering.

**Ops runner (host).** It watches `ops/requests/` for retrain requests. When one arrives it checks that enough memory is free, moves the cutoff to the request's simulated time, runs the batch pipeline, smoke-tests the new champion and rolls back if that fails. The plan is to pause the frontend and Grafana during the batch once the compose stack exists (Stage 13), so batch and the full serve stack never run together on 8 GB. The runner does not commit `dvc.lock`; the MLflow run records the commit, the cutoff and the pipeline run id instead. I run it on the host because starting containers from inside a container needs the Docker socket, and I don't want to hand that to any container.

**Prometheus, Pushgateway and node-exporter.** Prometheus scrapes every component every 15 seconds: the frontend, backend and model server, the MLflow server, the Pushgateway, node-exporter, and Prometheus, Alertmanager and Grafana themselves. The pipeline pushes its stage metrics to the Pushgateway, because batch jobs are too short-lived to be scraped. The Pushgateway runs in both compose profiles and saves its values to a file, so numbers pushed during a batch are still there when the serve stack comes back. node-exporter reports host RAM and CPU.

**Alertmanager.** It routes drift and error alerts to the backend webhook. The backend logs them, and drift alerts create a retrain request. This closes the loop from monitoring to alert to retraining.

**Grafana.** Its dashboards are provisioned from JSON and refresh every 15 seconds.

**DVC local remote, Git and Docker Hub.** DVC holds data and model versions, git holds code and the pipeline lock, and Docker Hub holds the published multi-arch images. Docker Hub stores images and nothing else.
