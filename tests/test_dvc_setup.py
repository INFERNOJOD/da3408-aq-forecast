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
