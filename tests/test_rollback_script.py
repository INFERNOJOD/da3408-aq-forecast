import pytest
from scripts import rollback
from src.pipeline.registry import ModelRegistryClient


@pytest.fixture
def two_versions(tmp_path, monkeypatch):
    uri = f"sqlite:///{tmp_path / 'reg.db'}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    reg = ModelRegistryClient("aq-pm25", uri)  # the name in params.yaml
    reg.client.create_registered_model("aq-pm25")
    reg.promote("file:///nowhere/1", "run1", {})
    reg.promote("file:///nowhere/2", "run2", {})
    return reg


def test_rollback_moves_champion_back(two_versions, capsys):
    assert rollback.main([]) == 0
    assert "champion: 2 -> 1" in capsys.readouterr().out
    assert two_versions.champion_version() == "1"


def test_rollback_to_missing_version_exits_with_error(two_versions):
    assert rollback.main(["--version", "7"]) == 1
    assert two_versions.champion_version() == "2"


def test_list_shows_versions(two_versions, capsys):
    assert rollback.main(["--list"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("2 champion") and out[1].startswith("1 previous")
