#!/usr/bin/env bash
# First set-up of a fresh clone: settings, certificates, Python, data and the
# first model. Run it once, before the first "docker compose ... up".
#
#   scripts/bootstrap.sh
#
# Steps, in order (each one is skipped when its result is already there):
#   1. .env from .env.example, with a random OPS_API_KEY and Grafana password,
#      HOST_PROJECT set to this folder and HOST_UID/HOST_GID to my user
#   2. certs/ from scripts/make_certs.sh
#   3. uv sync --frozen: the pinned Python environment in .venv
#   4. dvc pull data/raw.dvc: the raw CSVs from the DVC remote in .dvc/config
#   5. dvc repro: the whole pipeline. With an empty registry the register stage
#      makes version 1 of aq-pm25 the champion (only the baseline limit applies)
#   6. check that the registry has a champion, which the model server needs
#
# git holds the code and DVC the data, but the MLflow registry (mlflow.db,
# mlruns/) is local state in neither, so a fresh clone has no model to serve.
# Without step 5 the model server never passes its health check and the backend
# never starts (final audit, 2026-10-27).
#
# Needs docker, uv, java 17 (Spark) and openssl. Refuses while this project's
# serve stack runs: Spark and the stack together do not fit in 8 GB (CLAUDE.md).
# Exit codes: 0 ready, 1 a step failed, 3 the serve stack is running.
set -euo pipefail

cd "$(dirname "$0")/.."
project=$(pwd -P)
run="uv run --frozen"

say() { printf '\n== %s\n' "$*"; }
fail() { echo "bootstrap: $*" >&2; exit 1; }

for tool in docker uv java openssl; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is not installed"
done

if [[ -n "$(docker compose --profile serve ps -q 2>/dev/null)" ]]; then
    echo "bootstrap refused: the serve stack is running and Spark needs its memory." >&2
    echo "Run 'docker compose --profile serve stop' first." >&2
    exit 3
fi

say "1/6 settings (.env)"
if [[ -f .env ]]; then
    grep -q "^HOST_PROJECT=$project\$" .env \
        || fail ".env exists but HOST_PROJECT is not $project; fix it by hand"
    echo ".env exists, kept as it is"
else
    sed -e "s|^OPS_API_KEY=.*|OPS_API_KEY=$(openssl rand -hex 24)|" \
        -e "s|^GRAFANA_ADMIN_PASSWORD=.*|GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 12)|" \
        -e "s|^HOST_PROJECT=.*|HOST_PROJECT=$project|" \
        -e "s|^HOST_UID=.*|HOST_UID=$(id -u)|" \
        -e "s|^HOST_GID=.*|HOST_GID=$(id -g)|" \
        .env.example > .env
    chmod 600 .env
    echo "wrote .env with a new random OPS_API_KEY (the operator key for the console)"
fi

say "2/6 certificates (certs/)"
if [[ -f certs/ca.crt && -f certs/server.crt && -f certs/server.key ]]; then
    echo "certs/ exists, kept as it is"
else
    scripts/make_certs.sh
fi

say "3/6 Python environment (uv sync --frozen)"
uv sync --frozen

say "4/6 raw data (dvc pull data/raw.dvc)"
$run dvc pull data/raw.dvc

has_champion() {
    [[ -f mlflow.db ]] && $run python -m scripts.rollback --list 2>/dev/null \
        | grep -qw champion
}

say "5/6 first pipeline run (dvc repro)"
if has_champion; then
    echo "the registry already has a champion; nothing to train"
else
    # The Pushgateway is in the batch profile too, so the first run's stage
    # times also reach Grafana. It is small (64 MB) and keeps running.
    docker compose --profile batch up -d pushgateway
    PIPELINE_TRIGGER=initial $run dvc repro
fi

say "6/6 registry check"
has_champion || fail "no champion in the registry; see the dvc repro output above"
$run python -m scripts.rollback --list

cat <<'EOF'

Ready. Start the app and the ops runner:
  docker compose --profile serve up -d
  uv run --frozen python -m src.ops.runner
Then open https://localhost (docs/user_manual.md explains the certificate warning).
EOF
