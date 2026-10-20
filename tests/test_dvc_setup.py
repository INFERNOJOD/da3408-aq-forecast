"""Checks that data versioning is configured (Stage 3)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_raw_data_is_tracked_by_dvc():
    meta = yaml.safe_load((ROOT / "data" / "raw.dvc").read_text())
    assert meta["outs"][0]["path"] == "raw"
    assert meta["outs"][0]["nfiles"] == 5


def test_remote_is_local_path_not_cloud():
    config = (ROOT / ".dvc" / "config").read_text()
    assert "url = /" in config
    for scheme in ("s3://", "gs://", "azure://", "http"):
        assert scheme not in config


def test_raw_data_not_in_git_index():
    ignore = (ROOT / ".gitignore").read_text()
    assert "/data/raw/" in ignore


def test_mlproject_points_at_the_train_stage_with_a_pinned_env():
    project = yaml.safe_load((ROOT / "MLproject").read_text())
    assert project["python_env"] == "python_env.yaml"
    assert project["entry_points"]["main"]["command"] == "python -m src.pipeline.train"
    env = yaml.safe_load((ROOT / "python_env.yaml").read_text())
    assert env["python"].startswith("3.12")
    assert all("==" in dep for dep in env["dependencies"])


def test_pinned_env_matches_the_lock_file():
    lock = (ROOT / "uv.lock").read_text()
    env = yaml.safe_load((ROOT / "python_env.yaml").read_text())
    for dep in env["dependencies"]:
        name, version = dep.split("==")
        assert f'name = "{name}"\nversion = "{version}"' in lock, dep
