import subprocess

import numpy as np
import pandas as pd
import pytest
from src.common import versioning
from src.common.errors import ConfigError


def test_dvc_raw_md5(tmp_path):
    f = tmp_path / "raw.dvc"
    f.write_text("outs:\n- md5: abc123.dir\n  path: raw\n")
    assert versioning.dvc_raw_md5(f) == "abc123.dir"


def test_dvc_raw_md5_errors(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        versioning.dvc_raw_md5(tmp_path / "none.dvc")
    bad = tmp_path / "bad.dvc"
    bad.write_text("outs: []\n")
    with pytest.raises(ConfigError, match="No data hash"):
        versioning.dvc_raw_md5(bad)


def make_data(path, order=(0, 1, 2), value=3.0):
    df = pd.DataFrame(
        {
            "City": ["A", "A", "B"],
            "Datetime": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-01"]),
            "x": [1.0, np.nan, value],
        }
    )
    df.iloc[list(order)].to_parquet(path, index=False)


def test_parquet_data_md5_ignores_layout_and_row_order(tmp_path):
    make_data(tmp_path / "a.parquet")
    make_data(tmp_path / "b.parquet", order=(2, 0, 1))  # same rows, other order
    assert versioning.parquet_data_md5(
        tmp_path / "a.parquet"
    ) == versioning.parquet_data_md5(tmp_path / "b.parquet")


def test_parquet_data_md5_reads_a_folder_of_part_files(tmp_path):
    folder = tmp_path / "data.parquet"
    folder.mkdir()
    make_data(folder / "part-00000-aaa.parquet")
    first = versioning.parquet_data_md5(folder)
    (folder / "part-00000-aaa.parquet").rename(folder / "part-00000-zzz.parquet")
    assert versioning.parquet_data_md5(folder) == first  # a new random id, same data


def test_parquet_data_md5_changes_when_a_value_changes(tmp_path):
    make_data(tmp_path / "a.parquet")
    make_data(tmp_path / "b.parquet", value=3.5)
    assert versioning.parquet_data_md5(
        tmp_path / "a.parquet"
    ) != versioning.parquet_data_md5(tmp_path / "b.parquet")


def test_parquet_data_md5_errors(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        versioning.parquet_data_md5(tmp_path / "missing")
    make_data(tmp_path / "a.parquet")
    with pytest.raises(ConfigError, match="missing columns"):
        versioning.parquet_data_md5(tmp_path / "a.parquet", sort_by=("nope",))


def test_git_commit_and_dirty_in_a_temp_repo(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    (tmp_path / "a.txt").write_text("one")
    git("add", "a.txt")
    git("commit", "-q", "-m", "first")
    monkeypatch.chdir(tmp_path)
    assert len(versioning.git_commit()) == 40
    assert versioning.git_dirty() is False
    (tmp_path / "a.txt").write_text("two")
    assert versioning.git_dirty() is True
    (tmp_path / "untracked.txt").write_text("x")  # untracked files do not count
    git("checkout", "a.txt")
    assert versioning.git_dirty() is False


def test_git_outside_a_repo_gives_unknown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert versioning.git_commit() == "unknown"
