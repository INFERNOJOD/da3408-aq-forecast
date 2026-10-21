#!/usr/bin/env bash
# Local CI: lint, tests, and a check that the DVC pipeline and remote match git.
#
#   scripts/ci.sh            # ruff, pytest, dvc status (about 1 min)
#   scripts/ci.sh --repro    # also dvc repro + dvc push first (batch work)
#
# The project may not use a cloud CI service, so this script is the CI. I run
# it before every stage commit; the pre-commit hook runs the fast part (ruff
# and pytest) on each commit.
#
# Checks, in order:
#   ruff check, ruff format --check, pytest (JUnit XML for the test report),
#   with --repro: dvc repro and dvc push (only if lint and tests passed,
#   so broken code never trains a model),
#   dvc status: dvc.lock matches the code, params and data in the workspace,
#   dvc status -c: every output in dvc.lock is in the local DVC remote, so any
#   commit can be restored later with "git checkout <commit> && dvc pull".
#
# --repro refuses to start while the serve stack is up: Spark plus the serve
# containers do not fit in 8 GB (CLAUDE.md). Stop it first with
# "docker compose --profile serve stop".
#
# Writes reports/ci/last_run.log and reports/ci/junit.xml (CI_OUT_DIR
# overrides the folder, which the tests use). Exit codes: 0 all checks passed,
# 1 a check failed, 2 bad option, 3 serve stack is running.
set -uo pipefail

cd "$(dirname "$0")/.."

usage() {
    sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'
}

repro=0
for arg in "$@"; do
    case "$arg" in
        --repro) repro=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $arg" >&2; usage >&2; exit 2 ;;
    esac
done

serve_running() {
    command -v docker >/dev/null 2>&1 \
        && [[ -n "$(docker compose --profile serve ps -q 2>/dev/null)" ]]
}

if [[ $repro -eq 1 ]] && serve_running; then
    echo "--repro refused: the serve stack is running and Spark needs its memory." >&2
    echo "Run 'docker compose --profile serve stop' first." >&2
    exit 3
fi

out="${CI_OUT_DIR:-reports/ci}"
mkdir -p "$out"
exec > >(tee "$out/last_run.log") 2>&1

run="uv run --frozen"
failed=0
summary=()

# step NAME CMD...: run one check, record PASS/FAIL and its duration.
step() {
    local name=$1 t0=$SECONDS result
    shift
    echo
    echo "== $name: $*"
    if "$@"; then result=PASS; else result=FAIL; failed=1; fi
    summary+=("$(printf '%-14s %s %5ds' "$name" "$result" $((SECONDS - t0)))")
}

# dvc status exits 0 even when stages are out of date, so read its message.
dvc_clean() {
    local text
    text=$($run dvc status "$@") || return 1
    echo "$text"
    grep -qE "Data and pipelines are up to date|are in sync" <<<"$text"
}

commit=$(git rev-parse --short HEAD)
dirty=$([[ -n "$(git status --porcelain --untracked-files=no)" ]] && echo yes || echo no)
echo "CI run $(date '+%Y-%m-%d %H:%M:%S')  commit $commit  uncommitted changes: $dirty" \
     " mode: $([[ $repro -eq 1 ]] && echo repro || echo check)"

step ruff         $run ruff check .
step ruff-format  $run ruff format --check .
step pytest       $run pytest -q -p no:cacheprovider --junitxml="$out/junit.xml"

if [[ $repro -eq 1 ]]; then
    if [[ $failed -eq 0 ]]; then
        export PIPELINE_TRIGGER=ci PIPELINE_RUN_ID="ci-$(date +%Y%m%d-%H%M%S)"
        step dvc-repro $run dvc repro
        step dvc-push  $run dvc push
    else
        summary+=("$(printf '%-14s %s' dvc-repro 'SKIP (lint or tests failed)')")
    fi
fi

step dvc-status   dvc_clean
step dvc-remote   dvc_clean -c

echo
echo "== summary (commit $commit)"
printf '%s\n' "${summary[@]}"
if [[ $failed -eq 0 ]]; then echo "CI PASSED"; else echo "CI FAILED"; fi
exit $failed
