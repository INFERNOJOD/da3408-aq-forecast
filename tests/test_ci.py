import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / "scripts" / "ci.sh"


def run_ci(*args, path=None, tmp_path=None):
    env = dict(os.environ)
    if path is not None:
        env["PATH"] = f"{path}:{env['PATH']}"
    if tmp_path is not None:
        env["CI_OUT_DIR"] = str(tmp_path / "ci")
    return subprocess.run(
        ["bash", str(CI), *args], capture_output=True, text=True, env=env, timeout=30
    )


def fake_docker(tmp_path, container_ids):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(f"#!/bin/sh\nprintf '{container_ids}'\n")
    docker.chmod(0o755)
    return bin_dir


def test_ci_script_is_valid_bash_and_executable():
    assert subprocess.run(["bash", "-n", str(CI)]).returncode == 0
    assert os.access(CI, os.X_OK)


def test_ci_help_lists_both_modes():
    result = run_ci("--help")
    assert result.returncode == 0
    assert "scripts/ci.sh --repro" in result.stdout


def test_ci_rejects_unknown_option():
    result = run_ci("--nope")
    assert result.returncode == 2
    assert "unknown option" in result.stderr


def test_ci_repro_refused_while_serve_stack_runs(tmp_path):
    bin_dir = fake_docker(tmp_path, "abc123\\n")
    result = run_ci("--repro", path=bin_dir, tmp_path=tmp_path)
    assert result.returncode == 3
    assert "serve stack is running" in result.stderr
    # Refused before any check ran, so no log was started.
    assert not (tmp_path / "ci").exists()


def test_ci_runs_every_check_in_order():
    text = CI.read_text()
    steps = re.findall(r"^\s*step (\S+)", text, flags=re.M)
    assert steps == [
        "ruff",
        "ruff-format",
        "pytest",
        "dvc-repro",
        "dvc-push",
        "dvc-status",
        "dvc-remote",
    ]
    assert "--junitxml=" in text


def test_pre_commit_hooks_are_local_and_cover_lint_tests_and_data():
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    (repo,) = config["repos"]
    assert repo["repo"] == "local"
    hooks = {hook["id"]: hook for hook in repo["hooks"]}
    assert set(hooks) == {"ruff-check", "ruff-format", "pytest", "no-data-or-secrets"}
    guard = re.compile(hooks["no-data-or-secrets"]["files"])
    for path in ["data/raw/city_hour.csv", "certs/ca.key", ".env", "mlflow.db"]:
        assert guard.search(path), path
    for path in ["data/raw.dvc", ".env.example", "src/backend/app.py"]:
        assert not guard.search(path), path
    tests_trigger = re.compile(hooks["pytest"]["files"])
    assert tests_trigger.search("src/backend/app.py")
    assert tests_trigger.search("docker-compose.yml")
    assert not tests_trigger.search("docs/PLAN.md")
