import subprocess

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


def test_dir_md5_changes_with_content_and_ignores_checksum_files(tmp_path):
    d = tmp_path / "data.parquet"
    d.mkdir()
    (d / "part-0").write_bytes(b"abc")
    first = versioning.dir_md5(d)
    assert versioning.dir_md5(d) == first
    (d / ".part-0.crc").write_bytes(b"ignored")  # Spark checksum file
    assert versioning.dir_md5(d) == first
    (d / "part-0").write_bytes(b"abd")
    assert versioning.dir_md5(d) != first


def test_dir_md5_missing_path(tmp_path):
    with pytest.raises(ConfigError):
        versioning.dir_md5(tmp_path / "missing")


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
