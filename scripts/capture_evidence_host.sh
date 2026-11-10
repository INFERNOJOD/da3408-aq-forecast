#!/usr/bin/env bash
# Host half of the evidence gallery (docs/evidence/). The browser half is
# scripts/capture_evidence.py, which runs in the Playwright container.
#
#   scripts/capture_evidence_host.sh terminals   # command outputs -> .txt files
#   scripts/capture_evidence_host.sh shoot JOB   # run one browser job in the container
#
# Each .txt starts with two comment lines (when, and what it proves) and the
# command as "$ ...". Commands that need the operator key show the literal
# text $OPS_API_KEY; the value comes from .env through the environment and is
# never written out. Every file is checked for the key and the Grafana
# password afterwards.
set -uo pipefail
cd "$(dirname "$0")/.."

EV=docs/evidence
CONTAINER=aq-evidence
OPS_API_KEY=$(grep '^OPS_API_KEY=' .env | cut -d= -f2-)
GRAFANA_PW=$(grep '^GRAFANA_ADMIN_PASSWORD=' .env | cut -d= -f2-)
export OPS_API_KEY
CACERT=certs/ca.crt
B=https://localhost:8000

# scrub FILE: stop if a secret ended up in a file.
scrub() {
    if grep -qF -- "$OPS_API_KEY" "$1" || { [[ -n $GRAFANA_PW ]] && grep -qF -- "$GRAFANA_PW" "$1"; }; then
        echo "SECRET FOUND in $1, deleting it" >&2
        rm -f "$1"
        return 1
    fi
}

# cap SECTION NAME PROVES COMMAND: run COMMAND in bash, save it as a transcript.
cap() {
    local sec=$1 name=$2 proves=$3 cmd=$4 out
    out="$EV/$sec/$name.txt"
    mkdir -p "$EV/$sec"
    {
        echo "# captured $(date '+%Y-%m-%d %H:%M:%S %Z') on the project VM, commit $(git rev-parse --short HEAD)"
        echo "# what this proves: $proves"
        echo "\$ $cmd"
        bash -c "$cmd" 2>&1 | sed -e 's/\x1b\[[0-9;]*m//g' -e 's/.*\r//'
    } > "$out"
    scrub "$out" && echo "wrote $out"
}

shoot() {
    docker exec -e OPS_API_KEY "$CONTAINER" python scripts/capture_evidence.py "$@"
}

# no_cloud_cap SECTION NAME: the no-cloud transcript (also used by "nocloud").
no_cloud_cap() {
    cap "$1" "$2" "no cloud service is used: the one cloud SDK in uv.lock, databricks-sdk, comes in with MLflow itself and my code never imports it; the DVC remote and the MLflow store are local folders" \
        "echo 'cloud SDK packages in uv.lock:'; grep -iE '^name = \"(boto3|botocore|google-cloud[a-z-]*|azure[a-z-]*|sagemaker|databricks[a-z-]*)\"' uv.lock; echo; echo 'why it is there:'; uv tree --frozen --invert --package databricks-sdk; echo; echo 'lines in src/ that mention databricks:'; grep -rn databricks src --include='*.py' | wc -l; echo; uv run --frozen dvc remote list; grep -n 'MLFLOW_TRACKING_URI\|backend-store-uri\|default-artifact-root' docker-compose.yml"
}

terminals() {
    local s

    s=02_pipeline_viz
    cap $s 13_pipeline_api "the console reads the same public REST endpoints (stages, runs, models)" \
        "curl -s --cacert $CACERT $B/pipeline/stages | jq -c '.run_id, (.stages[] | {name,status,duration_s,rows_out,rows_per_sec})'; curl -s --cacert $CACERT '$B/pipeline/runs?limit=5' | jq -c '.runs[] | {run_id,trigger,status,failed_stage,error: (.error // \"\" | .[0:110])}'"

    s=03_design
    cap $s 30_frontend_never_imports_backend "loose coupling: no frontend module imports backend code; the URL is configurable" \
        "grep -rn 'src.backend\|from src import backend' src/frontend/ || echo 'no imports of src.backend in src/frontend'; grep -n BACKEND_URL src/frontend/client.py docker-compose.yml"
    cap $s 31_docs_folder "the mandatory design documents exist" \
        "ls -l docs/*.md docs/img"

    s=04_implementation
    cap $s 20_ruff "standard Python style: ruff lint (pycodestyle, pyflakes, pydocstyle, ...) and format both pass" \
        "uv run --frozen ruff check . && uv run --frozen ruff format --check . && grep -n -A12 '\[tool.ruff' pyproject.toml"
    cap $s 21_logging_everywhere "every module logs through the logging module (no print)" \
        "grep -rln --include='*.py' 'get_logger(__name__)\|logging.getLogger' src | sort; echo; echo 'print( calls in src:'; grep -rn '^\s*print(' src | wc -l"
    cap $s 22_api_tests_match_lld "the code is held to the LLD by tests (routes, features, metrics, alerts, signature)" \
        "uv run --frozen pytest -p no:cacheprovider -k 'lld or signature_matches or alert_rules_match' --disable-warnings -v 2>/dev/null | grep -E 'PASSED|FAILED|passed|failed'"
    cap $s 23_error_body_live "exception handling live: wrong input gives the LLD error body, not a stack trace" \
        "for p in '/forecast?city=Pune' '/forecast' '/nope'; do curl -s -w '  -> HTTP %{http_code}\n' --cacert $CACERT \"$B\$p\"; done; curl -s -w '  -> HTTP %{http_code}\n' --cacert $CACERT -X DELETE $B/health"

    s=05_testing
    cap $s 10_pytest_full "the full unit/integration suite: number of tests passed and failed" \
        "uv run --frozen pytest -q -p no:cacheprovider --disable-warnings 2>/dev/null"
    cap $s 11_pytest_collect "the list of every test case (pytest --collect-only)" \
        "uv run --frozen pytest --collect-only -q -p no:cacheprovider 2>&1 | grep -v '^$'"
    cap $s 12_tests_per_module "a test file for every module" \
        "ls tests/; echo; for f in tests/test_*.py; do printf '%-45s %s\n' \$f \$(grep -c '^def test_\|^    def test_' \$f); done"

    s=06_data_engineering
    cap $s 20_spark_repro_log "Spark ingest/validate/features output with stage times and rows/sec (recorded CI dvc repro of 2026-10-21, not rerun today)" \
        "grep -v '^\.\|warnings summary\|Warning\|color_warning\|^  ' reports/ci/stage16/repro_run.log | sed -n '/dvc-repro/,\$p' | grep -v '^\[Stage'"
    cap $s 21_stage_metrics "the last pipeline run's per-stage records: seconds, rows in/out, rows per second" \
        "for f in ingest validate features train evaluate test register; do jq -c '{stage, status, duration_s, rows_in, rows_out, rows_per_sec, run_id}' reports/stage_metrics/\$f.json; done"
    cap $s 22_csv_to_parquet "ingest turns 283 MB of CSV into 65 MB of Parquet" \
        "du -sh data/raw data/interim data/features; ls -l data/raw; ls data/interim"
    cap $s 23_throughput_history "every stage run recorded with throughput (reports/runs.jsonl)" \
        "jq -r 'select(.stage==\"ingest\" or .stage==\"validate\" or .stage==\"features\") | [.started_at,.stage,.status,.duration_s,.rows_out,.rows_per_sec] | @tsv' reports/runs.jsonl | column -t | tail -30"

    s=07_source_control_ci
    cap $s 01_dvc_dag "the DVC DAG is the CI pipeline: ingest -> validate -> features -> train -> evaluate -> test -> register" \
        "uv run --frozen dvc dag"
    cap $s 03_dvc_status "dvc.lock matches the code, params and data in the workspace" \
        "uv run --frozen dvc status"
    cap $s 04_dvc_status_remote "every output in dvc.lock is in the DVC remote" \
        "uv run --frozen dvc status -c"
    cap $s 05_dvc_remote "DVC remote is a local folder (no cloud)" \
        "uv run --frozen dvc remote list; cat .dvc/config"
    cap $s 06_git_log "Git history: one commit per stage with clear messages" \
        "git log --oneline | wc -l; git log --date=short --format='%h %ad %s' | head -70"
    cap $s 07_data_versioned_by_dvc "raw data is versioned by DVC, not git: git holds only the .dvc pointer and dvc.lock hashes" \
        "cat data/raw.dvc; echo; git ls-files data; echo; git check-ignore -v data/raw/city_hour.csv; echo; grep -n -B1 -A4 'path: data/raw\|path: models/candidate' dvc.lock | head -30"
    cap $s 08_model_versions_in_git "model and data versions change with dvc.lock commits" \
        "git log --date=short --format='%h %ad %s' -- dvc.lock | head -20"
    cap $s 20_ci_run "local CI (cloud CI is not allowed): ruff, format, pytest, dvc status, dvc status -c all pass" \
        "scripts/ci.sh"

    s=08_experiment_tracking
    cap $s 20_champion_run_tags "beyond autolog: git commit, dirty flag, data md5, features md5, cutoff, trigger, gate result on the run" \
        "MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen python -c \"import mlflow; r=mlflow.MlflowClient('http://localhost:5000').get_run('498b149f78e2418695c3bf7e01b91615'); [print(f'tag    {k} = {v}') for k,v in sorted(r.data.tags.items()) if not k.startswith('mlflow.log')]; [print(f'param  {k} = {v}') for k,v in sorted(r.data.params.items())]\""
    cap $s 21_champion_run_metrics "metrics incl. per-city MAE, baselines and drift numbers" \
        "MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen python -c \"import mlflow; r=mlflow.MlflowClient('http://localhost:5000').get_run('498b149f78e2418695c3bf7e01b91615'); [print(f'{k:45s} {v:.4f}') for k,v in sorted(r.data.metrics.items())]\""
    cap $s 22_all_runs "all tracked runs with their trigger, gate result and reproducibility tags" \
        "MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen python -c \"
import mlflow
c = mlflow.MlflowClient('http://localhost:5000')
for r in c.search_runs(['1'], max_results=100, order_by=['attributes.start_time DESC']):
    t = r.data.tags; m = r.data.metrics
    print(r.info.run_id[:12], r.info.status[:8].ljust(8), t.get('stage','-').ljust(8), t.get('trigger','-').ljust(7), t.get('promotion','-').ljust(9), 'v'+t.get('registry_version','-'), t.get('git_commit','-')[:7], t.get('cutoff','-'), round(m.get('chosen_mean_mae', float('nan')), 3))
\""
    cap $s 23_registry_aliases "model registry: versions with champion and previous aliases" \
        "MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen python -m scripts.rollback --list 2>&1 | grep -v INFO"

    s=09_monitoring
    cap $s 30_model_server_metrics "the model server (MLflow serving behind a metrics proxy) exports Prometheus metrics" \
        "docker compose exec -T model-server curl -s localhost:8001/metrics | grep -E '^(# HELP|# TYPE)? ?aq_' | head -40"
    cap $s 31_frontend_metrics "the Streamlit frontend exports Prometheus metrics" \
        "docker compose exec -T frontend curl -s localhost:8502/metrics | grep -E 'aq_' | head -30"
    cap $s 32_backend_metrics "the backend exports request, latency, drift, replay and model metrics" \
        "curl -s --cacert $CACERT $B/metrics | grep -E '^aq_' | head -60"
    cap $s 33_pushgateway_metrics "the pipeline pushes stage metrics through the Pushgateway" \
        "curl -s localhost:19091/metrics | grep -E '^aq_' | head -40"
    cap $s 34_mlflow_metrics "the MLflow server is scraped too" \
        "curl -s localhost:5000/metrics | grep -vE '^#' | head -15"
    cap $s 35_targets_api "all scrape targets are up" \
        "curl -s localhost:19090/api/v1/targets | jq -r '.data.activeTargets[] | [.labels.job, .scrapeUrl, .health, .lastScrapeDuration] | @tsv' | column -t"
    cap $s 36_promtool_rules "alert rules are valid and unit-tested with promtool" \
        "docker run --rm -v \$PWD/monitoring:/m:ro --entrypoint promtool prom/prometheus:v3.5.0 check rules /m/alerts.yml; docker run --rm -v \$PWD/monitoring:/m:ro -w /m --entrypoint promtool prom/prometheus:v3.5.0 test rules alerts_test.yml"
    cap $s 37_retention_scrape "retention 2 days, scrape interval 15 s" \
        "grep -n 'retention' docker-compose.yml; grep -n 'interval' monitoring/prometheus.yml"

    s=10_packaging
    cap $s 20_compose_ps "docker compose: frontend and backend are separate services, all healthy" \
        "docker compose --profile serve ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'"
    cap $s 21_docker_stats "every container runs under its mem_limit" \
        "docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}'"
    cap $s 22_docker_images "the project images" \
        "docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}' | grep -E 'REPOSITORY|aq-|infernogod'"
    cap $s 23_dockerhub_inspect "Docker Hub: all 5 images are published for linux/amd64 and linux/arm64" \
        "for i in aq-frontend aq-backend aq-model-server aq-mlflow aq-pipeline; do docker buildx imagetools inspect infernogod/\$i:0.1.0 | grep -E 'Name:|Digest:|Platform:' | grep -v 'unknown/unknown' | head -8; echo; done"
    cap $s 24_model_serving "MLflow model serving answers /ping and /invocations with predictions and the model version" \
        "docker compose exec -T model-server sh -c 'curl -s -w \" HTTP %{http_code}\n\" localhost:5001/ping; curl -s -X POST localhost:5001/invocations -H \"Content-Type: application/json\" -d \"{\\\"dataframe_split\\\":{\\\"columns\\\":[\\\"horizon_h\\\",\\\"city_code\\\",\\\"hour\\\",\\\"dow\\\",\\\"month\\\",\\\"is_weekend\\\",\\\"pm25_lag_1\\\",\\\"pm25_lag_2\\\",\\\"pm25_lag_3\\\",\\\"pm25_lag_24\\\",\\\"pm25_lag_168\\\",\\\"pm25_roll_mean_6\\\",\\\"pm25_roll_mean_24\\\",\\\"pm25_roll_std_24\\\",\\\"pm10_lag_1\\\",\\\"no2_lag_1\\\",\\\"co_lag_1\\\",\\\"so2_lag_1\\\",\\\"o3_lag_1\\\"],\\\"data\\\":[[1,0,9,2,3,0,80.0,82.0,85.0,90.0,95.0,84.0,88.0,10.0,150.0,40.0,1.2,12.0,30.0],[24,0,9,2,3,0,80.0,82.0,85.0,90.0,95.0,84.0,88.0,10.0,150.0,40.0,1.2,12.0,30.0]]}}\"; echo'"
    cap $s 25_backend_forecast "FastAPI serves the forecast the UI needs, with model version, run ID and git commit" \
        "curl -s --cacert $CACERT '$B/forecast?city=Delhi' | jq ."
    cap $s 26_mlproject_entry_points "MLproject: entry points run in the pinned python_env, the same versions as dev (uv.lock)" \
        "cat MLproject; echo; cat python_env.yaml; echo; uv run --frozen python --version; grep -E '^(name = \"(lightgbm|mlflow|pyspark|scikit-learn)\")' -A1 uv.lock"
    cap $s 27_health "the backend health endpoint reports the model server and the served version" \
        "curl -s --cacert $CACERT $B/health | jq ."

    s=11_guidelines
    cap $s 01_reproducibility_tags "every model traces to git commit + MLflow run ID + data version" \
        "curl -s --cacert $CACERT '$B/forecast?city=Delhi' | jq '.model'; MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen python -c \"import mlflow; t=mlflow.MlflowClient('http://localhost:5000').get_run('498b149f78e2418695c3bf7e01b91615').data.tags; [print(k, '=', t[k]) for k in ['git_commit','git_dirty','dvc_data_md5','features_md5','cutoff','trigger','pipeline_run_id']]\"; git show -s --format='%h %ad %s' --date=short b2eff79"
    cap $s 10_rollback_cli "rollback is one command; versions and aliases listed" \
        "MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen python -m scripts.rollback --help 2>&1 | grep -v INFO; MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen python -m scripts.rollback --list 2>&1 | grep -v INFO"
    cap $s 40_https_redirect "http and the old :8501 address redirect to https" \
        "curl -sI http://localhost/forecast | head -3; curl -sI http://localhost:8501/ | head -3"
    cap $s 41_tls_certificate "TLS: the frontend and backend serve certificates signed by the project CA, and the chain verifies" \
        "for h in localhost:443 localhost:8000; do echo \"== \$h\"; echo | openssl s_client -connect \$h -servername localhost -CAfile $CACERT 2>/dev/null | grep -E 'subject=|issuer=|Verify return code|Protocol|Cipher' | sort -u; done"
    cap $s 42_ops_auth "the ops endpoints need the API key: 401 without it, 401 with a wrong one, 200 with the key" \
        "curl -s -w '  -> HTTP %{http_code}\n' --cacert $CACERT $B/ops/drift | cut -c1-200; curl -s -w '  -> HTTP %{http_code}\n' --cacert $CACERT -H 'Authorization: Bearer wrong' $B/ops/replay; curl -s -o /dev/null -w 'with the key -> HTTP %{http_code}\n' --cacert $CACERT -H \"Authorization: Bearer \$OPS_API_KEY\" $B/ops/replay"
    cap $s 43_secrets_not_in_git ".env and the certificates are ignored; the key is in no tracked file and nowhere in the git history" \
        "git check-ignore -v .env certs/server.key; echo; echo 'tracked files named .env or under certs/:'; git ls-files | grep -E '(^|/)\.env$|^certs/' | wc -l; echo 'commits whose diff contains the key value:'; git log --all -p | grep -cF -- \"\$OPS_API_KEY\"; echo; cat .env.example 2>/dev/null || true"
    cap $s 44_non_root_containers "no container runs as root and none gets the Docker socket" \
        "for c in \$(docker compose --profile serve ps --format '{{.Service}}'); do printf '%-15s ' \$c; docker compose exec -T \$c id 2>/dev/null | cut -c1-60 || echo '(no id binary)'; done; echo; grep -n 'docker.sock' docker-compose.yml || echo 'docker.sock is not mounted anywhere'"
    cap $s 45_hmac_check "the key is compared in constant time (hmac.compare_digest)" \
        "grep -n -B4 -A8 'compare_digest' src/backend/app.py"
    no_cloud_cap $s 50_no_cloud
    cap $s 52_dockerhub_api "Docker Hub's own API lists every tag of the 5 images with linux/amd64 and linux/arm64 (the website blocks headless browsers with a Cloudflare check)" \
        "for i in aq-frontend aq-backend aq-model-server aq-mlflow aq-pipeline; do echo \"== infernogod/\$i\"; curl -s https://hub.docker.com/v2/namespaces/infernogod/repositories/\$i/tags | jq -c '.results[] | {tag: .name, platforms: [.images[] | select(.architecture != \"unknown\") | .os + \"/\" + .architecture], pushed: .tag_last_pushed}'; done"
    cap $s 51_dockerhub_tags "Docker Hub: the latest and 0.1.0 tags of every image point to the same multi-arch index" \
        "for i in aq-frontend aq-backend aq-model-server aq-mlflow aq-pipeline; do for t in 0.1.0 latest; do printf '%-34s ' infernogod/\$i:\$t; docker buildx imagetools inspect infernogod/\$i:\$t --format '{{.Manifest.Digest}}'; done; done"
}

# ---------------------------------------------------------------------------
# Live story: drift -> alert -> retrain -> gate -> served version -> rollback.
# The only part that changes state. It ends by restoring params.yaml, dvc.lock
# and reports/ from git, the DVC outputs from the cache, champion v4, and by
# removing the request files it created.
# ---------------------------------------------------------------------------
S=11_guidelines
C=https://localhost/console

auth_get() { curl -s --cacert $CACERT -H "Authorization: Bearer $OPS_API_KEY" "$B$1"; }

# wait_for SECONDS DESCRIPTION CHECK...: poll CHECK every 3 s.
wait_for() {
    local limit=$1 what=$2 t0=$SECONDS
    shift 2
    echo "waiting for: $what"
    until "$@"; do
        if (( SECONDS - t0 > limit )); then echo "TIMEOUT after ${limit}s: $what" >&2; return 1; fi
        sleep 3
    done
    echo "  ok after $((SECONDS - t0))s: $what"
}

drift_on() { [[ $(auth_get /ops/drift | jq -r .any_drift) == true ]]; }
alert_state() { curl -s localhost:19090/api/v1/alerts | jq -r '[.data.alerts[] | select(.labels.alertname=="PM25DriftHigh") | .state] | first // "none"'; }
alert_is() { [[ $(alert_state) == "$1" ]]; }
new_request() { ls -t ops/requests/*.json 2>/dev/null | head -1 | grep -qv -f "$EV/.requests_before"; }
latest_request() { ls -t ops/requests/*.json | head -1; }
request_status() { jq -r .status "$(latest_request)"; }
request_finished() { [[ $(request_status) =~ ^(done|failed|rolled_back)$ ]]; }
frontend_stopped() { [[ -z $(docker compose ps -q --status running frontend) ]]; }
# The version in a forecast answer comes from the model server itself (LLD 4).
served_version() { curl -s --cacert $CACERT "$B/forecast?city=Delhi" | jq -r .model.version; }
served_is() { [[ $(served_version) == "$1" ]]; }

story() {
    mkdir -p "$EV/$S"
    ls ops/requests/*.json > "$EV/.requests_before"
    [[ -e ops/episode.json ]] && echo "episode.json existed before" > "$EV/.episode_before"
    echo "champion before: $(served_version)"

    nohup uv run --frozen python -m src.ops.runner > "$EV/.runner.log" 2>&1 &
    echo $! > "$EV/.runner.pid"
    sleep 5
    cap $S 30_story_00_runner_started "the ops runner is running on the host and watches ops/requests/" \
        "pgrep -af 'src.ops.runner' | grep -v pgrep | cut -c1-120; head -5 $EV/.runner.log | cut -c1-160"

    shoot page --streamlit --url $C --wait-text Pipeline --key --click "Reset replay" --after-text "Replay reset" \
        --scroll "Replay reset" --target $S/30_story_01_replay_reset --source "$C  (Reset replay clicked)" \
        --proves "step 1: the operator resets the replay of the 2020 lockdown from the console"
    shoot page --streamlit --url $C --wait-text Pipeline --key --click "Start replay" --after-text "Replay started" \
        --scroll "Replay started" --target $S/30_story_02_replay_started --source "$C  (Start replay clicked)" \
        --proves "step 2: the replay starts, 1 simulated hour per second, as live traffic"

    wait_for 400 "drift rule true" drift_on || return 1
    shoot page --streamlit --url $C --wait-text Pipeline --key --scroll Drift \
        --target $S/30_story_03_drift_yes --source "$C  (key entered)" \
        --proves "step 3: drift detected = YES, enough cities above their own PSI threshold"
    cap $S 30_story_03_drift_api "step 3: the same drift report from GET /ops/drift" \
        "curl -s --cacert $CACERT -H \"Authorization: Bearer \$OPS_API_KEY\" $B/ops/drift | jq '{sim_time, any_drift, cities_exceeding, min_cities, mae_ratio_pooled}'"

    wait_for 120 "PM25DriftHigh pending" alert_is pending || true
    shoot page --url http://localhost:19090/alerts --wait-ms 3000 --full \
        --target $S/30_story_04_alert_pending --proves "step 4: PM25DriftHigh is pending in Prometheus (for: 1m)"
    wait_for 180 "PM25DriftHigh firing" alert_is firing || return 1
    shoot page --url http://localhost:19090/alerts --wait-ms 3000 --full \
        --target $S/30_story_05_alert_firing --proves "step 5: PM25DriftHigh is firing"
    shoot page --url "http://localhost:19093/#/alerts" --wait-ms 4000 --full \
        --target $S/30_story_06_alertmanager --proves "step 6: Alertmanager has the alert and sends it to the backend webhook"

    wait_for 180 "new retrain request" new_request || return 1
    cap $S 30_story_07_retrain_request "step 7: the webhook wrote a retrain request with the drift numbers and the simulated cutoff" \
        "cat \$(ls -t ops/requests/*.json | head -1)"
    shoot page --url "http://localhost:13000/d/aq-service?orgId=1&from=now-30m&to=now&kiosk" --wait-ms 8000 --full \
        --target $S/30_story_08_grafana_drift --proves "step 8: Grafana shows drift detected and the alert firing, near real time"

    wait_for 120 "frontend stopped by the runner" frontend_stopped || true
    shoot page --url https://localhost/ --wait-ms 2000 --full \
        --target $S/30_story_09_back_in_a_few_minutes \
        --proves "step 9: during the retrain the runner stops the frontend; users get this page, not an error"
    cap $S 30_story_10_compose_during_retrain "step 10: frontend and Grafana are stopped while Spark runs (8 GB limit)" \
        "docker compose --profile serve ps -a --format 'table {{.Service}}\t{{.Status}}'; echo; jq '{request_id, status, cutoff, started_at}' \$(ls -t ops/requests/*.json | head -1)"

    wait_for 900 "request finished" request_finished || return 1
    local req rid
    req=$(latest_request); rid=$(basename "$req" .json)
    cap $S 30_story_11_pipeline_log "step 11: dvc repro with the new cutoff: Spark stages with time and rows/sec, train, evaluate, gate" \
        "grep -vE '^\[Stage|WARN|setLogLevel|log level' ops/logs/$rid.log"
    cap $S 30_story_12_gate_decision "step 12: the gate compares the candidate with the champion on the same window" \
        "cat reports/gate.json; echo; cat reports/register.json"
    cap $S 30_story_13_request_final "step 13: the request ends with its result (promoted or rejected) and the smoke check" \
        "cat $req; echo; tail -15 $EV/.runner.log | cut -c1-200"
    wait_for 240 "frontend back" docker compose exec -T frontend curl -fs localhost:8501/_stcore/health || true
    sleep 5
    shoot page --streamlit --url $C --wait-text Pipeline --full \
        --target $S/30_story_14_console_after_retrain --source "$C" \
        --proves "step 14: the console shows the drift-triggered run, its stages and the model versions"
    story_served
    story_rollbacks

    shoot page --streamlit --url $C --wait-text Pipeline --key --click "Stop replay" --after-text "Replay stopped" \
        --scroll "Replay stopped" --target $S/30_story_20_replay_stopped --source "$C  (Stop replay clicked)" \
        --proves "step 20: replay stopped"
    shoot page --streamlit --url $C --wait-text Pipeline --key --click "Reset replay" --after-text "Replay reset" \
        --scroll "Replay reset" --target $S/30_story_21_replay_reset_again --source "$C  (Reset replay clicked)" \
        --proves "step 21: replay reset to 25 March 2020"
}

story_served() {
    cap $S 30_story_15_served_version "step 15: the version that serves forecasts after the gate" \
        "curl -s --cacert $CACERT $B/health | jq .; curl -s --cacert $CACERT '$B/forecast?city=Delhi' | jq '{issued_at, model, forecasts: [.forecasts[] | {horizon_h, pm25, aqi_category}]}'; MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen python -m scripts.rollback --list 2>&1 | grep -v INFO"

}

story_rollbacks() {
    shoot page --streamlit --url $C --wait-text Pipeline --key --fill "Version to restore (empty = the previous one)=1" \
        --click2 "Roll back" --after-text "Rolled back" --scroll "Rolled back" \
        --target $S/30_story_16_rollback_to_v1 --source "$C  (version 1, Roll back clicked)" \
        --proves "step 16: rollback from the console: champion moved to version 1"
    wait_for 180 "model server serves v1" served_is 1 || true
    cap $S 30_story_17_serving_v1 "step 17: the model server hot-swapped to version 1: the forecast now comes from v1" \
        "curl -s --cacert $CACERT '$B/forecast?city=Delhi' | jq -c '.model'; docker compose exec -T model-server curl -s localhost:8001/metrics | grep '^aq_model_loaded_version'; curl -s --cacert $CACERT $B/health | jq -c .; MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen python -m scripts.rollback --list 2>&1 | grep -v INFO"
    shoot page --streamlit --url $C --wait-text Pipeline --key --fill "Version to restore (empty = the previous one)=4" \
        --click2 "Roll back" --after-text "Rolled back" --scroll "Rolled back" \
        --target $S/30_story_18_rollback_to_v4 --source "$C  (version 4, Roll back clicked)" \
        --proves "step 18: and back: champion moved to version 4 again"
    wait_for 180 "model server serves v4" served_is 4 || true
    cap $S 30_story_19_serving_v4 "step 19: version 4 serves forecasts again" \
        "curl -s --cacert $CACERT '$B/forecast?city=Delhi' | jq -c '.model'; docker compose exec -T model-server curl -s localhost:8001/metrics | grep '^aq_model_loaded_version'; curl -s --cacert $CACERT $B/health | jq -c .; MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen python -m scripts.rollback --list 2>&1 | grep -v INFO"

}

restore() {
    [[ -f $EV/.runner.pid ]] && kill "$(cat $EV/.runner.pid)" 2>/dev/null
    pkill -f 'python -m src.ops.runner' 2>/dev/null
    git checkout -- params.yaml dvc.lock reports/ 2>/dev/null
    uv run --frozen dvc checkout 2>&1 | tail -3
    for f in ops/requests/*.json; do
        grep -qxF "$f" "$EV/.requests_before" || { echo "removing $f"; rm -f "$f"; }
    done
    [[ -e $EV/.episode_before ]] || { [[ -e ops/episode.json ]] && echo "removing ops/episode.json (did not exist before)" && rm -f ops/episode.json; }
    rm -f reports/drift_trigger.json
    uv run --frozen dvc status
    echo "served version: $(served_version)"
}

# code SECTION/NAME FILE PROVES [START END]: one rendered source file.
code() { shoot code --target "$1" --file "$2" --proves "$3" --start "${4:-1}" --end "${5:-0}"; }
# md SECTION/NAME FILE PROVES [HEADING]: one rendered Markdown file or section.
md() { if [[ -n ${4:-} ]]; then shoot md --target "$1" --file "$2" --proves "$3" --anchor "$4"; else shoot md --target "$1" --file "$2" --proves "$3"; fi; }

static_files() {
    code 06_data_engineering/13_bench_pandas_ingest scripts/bench_pandas_ingest.py "the pandas benchmark script that ran the same ingest job as Spark"
    code 07_source_control_ci/02_dvc_yaml dvc.yaml "dvc.yaml: the 7 CI stages with their deps, params and outputs"
    code 07_source_control_ci/09_gitignore .gitignore "data, MLflow store, secrets and certificates are kept out of git"
    code 07_source_control_ci/10_pre_commit .pre-commit-config.yaml "pre-commit hook runs ruff and pytest on every commit"
    code 07_source_control_ci/11_ci_sh scripts/ci.sh "the CI script: lint, tests, optional dvc repro + push, dvc status and dvc status -c"
    code 07_source_control_ci/12_params_yaml params.yaml "params.yaml: versioned pipeline parameters (cutoff, Spark, features, train)"
    code 08_experiment_tracking/30_train_logging src/pipeline/train.py "what train logs beyond autolog: tags, per-city error, drift numbers, artifacts" 1 140
    code 09_monitoring/40_prometheus_yml monitoring/prometheus.yml "Prometheus scrapes every component (backend, model server, frontend, pushgateway, MLflow, node, Alertmanager, Grafana)"
    code 09_monitoring/41_alerts_yml monitoring/alerts.yml "alert rules for drift, forecast error, 5xx rate, model server errors, targets down, failed stage"
    code 09_monitoring/42_alertmanager_yml monitoring/alertmanager.yml "Alertmanager routes every alert to the backend webhook over HTTPS"
    code 09_monitoring/43_alerts_test monitoring/alerts_test.yml "promtool unit tests for the alert rules"
    code 10_packaging/01_mlproject MLproject "MLproject: entry points for the pipeline in one pinned environment"
    code 10_packaging/02_python_env python_env.yaml "python_env.yaml: the Python version and pinned dependencies MLproject uses"
    code 10_packaging/03_docker_compose docker-compose.yml "docker compose: frontend and backend as separate services, mem_limit on each, serve and batch profiles"
    code 10_packaging/04_dockerfile_frontend docker/frontend/Dockerfile "frontend Dockerfile (copies only the frontend code)"
    code 10_packaging/05_dockerfile_backend docker/backend/Dockerfile "backend Dockerfile"
    code 10_packaging/06_dockerfile_model_server docker/model_server/Dockerfile "model server Dockerfile (MLflow model serving + metrics proxy)"
    code 10_packaging/07_dockerfile_mlflow docker/mlflow/Dockerfile "MLflow tracking server Dockerfile"
    code 10_packaging/08_dockerfile_pipeline docker/pipeline/Dockerfile "pipeline (Spark batch) Dockerfile"
    code 10_packaging/09_caddyfile docker/tls_proxy/Caddyfile "the TLS proxy config in front of the frontend"
    code 10_packaging/10_build_multiarch scripts/build_multiarch.sh "the script that built and pushed the amd64 + arm64 images"
    code 10_packaging/11_model_server_proxy src/model_server/supervisor.py "the model server loads aq-pm25@champion and hot-swaps on alias change" 1 80
    md 11_guidelines/02_reproduce_readme README.md "how to reproduce a model from its git commit and MLflow run ID, checked on v4" "## Reproduce a result"
    md 11_guidelines/03_ac6_reproducible docs/test_report.md "acceptance check AC-6: a rebuild gave the same hashes, MAE and model bytes" "### AC-6: reproducible from git commit + MLflow run ID: **met**"
    md 11_guidelines/04_eda docs/eda.md "EDA with figures: missing data, seasonality, lockdown effect, stations"
    md 11_guidelines/05_data_biases docs/eda.md "documented data biases and what I do about each" "## 4. Data biases and what I do about them"
    md 11_guidelines/06_data_notes docs/data_notes.md "data source, licence and city selection notes"
    code 11_guidelines/11_rollback_script scripts/rollback.py "rollback script: moves champion to previous or a named version"
    md 11_guidelines/12_ac5_rollback docs/test_report.md "acceptance check AC-5: rollback restores the previous champion" "### AC-5: rollback restores the previous champion: **met, after fixing D-1**"
    md 11_guidelines/13_failure_handling docs/HLD.md "failure handling: validation, gate rejection, smoke-check rollback, services down" "## 6. Failure handling"
    md 11_guidelines/20_ac3_drift docs/test_report.md "acceptance check AC-3: drift fires on the lockdown and never on normal weeks" "### AC-3: drift fires on the lockdown and not on normal weeks: **met**"
    code 11_guidelines/21_ops_runner src/ops/runner.py "automated retraining: the ops runner turns a request into dvc repro, then smoke-checks or rolls back" 1 30
    md 11_guidelines/22_retrain_e2e docs/metrics.md "the measured drift -> alert -> retrain -> promotion -> served loop (2 min 47 s)" "### End-to-end run: drift → alert → retrain → promotion → new model served"
    md 11_guidelines/46_security_hld docs/HLD.md "security design: API key, TLS with my own CA, secrets in .env, non-root containers" "**Security.**"
    md 11_guidelines/53_dockerhub_readme README.md "Docker Hub: the five published multi-arch images and their inspect output" "## Docker images"
}

final_state() {
    cap $S 30_story_23_final_state "after the story everything is back: v4 champion, v1 previous, replay stopped and reset, no new request files, dvc status clean, git clean, stack healthy" \
        "MLFLOW_DISABLE_AGENT_HINT=1 uv run --frozen python -m scripts.rollback --list 2>&1 | grep -v INFO; curl -s --cacert $CACERT $B/health | jq -c .; ls ops/requests; uv run --frozen dvc status; git status --short -- params.yaml dvc.lock reports/ ':!reports/ci' | wc -l; curl -s localhost:19090/api/v1/alerts | jq -c '[.data.alerts[] | {alert: .labels.alertname, state}]'; docker compose --profile serve ps --format '{{.Service}} {{.Status}}'"
}

case "${1:-}" in
    terminals) terminals ;;
    final) final_state ;;
    nocloud) no_cloud_cap 11_guidelines 16_no_cloud ;;
    shoot) shift; shoot "$@" ;;
    static) static_files ;;
    story) story ;;
    rollbacks) story_rollbacks ;;
    served) story_served ;;
    restore) restore ;;
    *) sed -n '2,6p' "$0"; exit 2 ;;
esac
