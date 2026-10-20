import pytest
from src.common.errors import RegistryError
from src.pipeline.registry import ModelRegistryClient


@pytest.fixture
def registry(tmp_path):
    """A registry in a throw-away SQLite database with an empty model entry."""
    reg = ModelRegistryClient("aq-test", f"sqlite:///{tmp_path / 'reg.db'}")
    reg.client.create_registered_model("aq-test")
    return reg


def promote(reg, n):
    """Register a dummy version (no real model files are needed for aliases)."""
    return reg.promote(f"file:///nowhere/{n}", f"run{n}", {"cutoff": f"c{n}"})


def test_no_champion_before_the_first_promotion(registry):
    assert registry.champion_version() is None
    assert registry.champion_uri() is None
    assert registry.previous_version() is None


def test_first_promotion_sets_champion_only(registry):
    assert promote(registry, 1) == "1"
    assert registry.champion_version() == "1"
    assert registry.previous_version() is None
    assert registry.champion_uri() == "models:/aq-test@champion"


def test_second_promotion_moves_the_old_champion_to_previous(registry):
    promote(registry, 1)
    promote(registry, 2)
    assert (registry.champion_version(), registry.previous_version()) == ("2", "1")
    rows = registry.versions()
    assert [r["version"] for r in rows] == ["2", "1"]  # newest first
    assert rows[0]["aliases"] == ["champion"] and rows[1]["aliases"] == ["previous"]
    assert rows[0]["tags"]["cutoff"] == "c2" and rows[0]["mlflow_run_id"] == "run2"


def test_rollback_defaults_to_previous_and_can_be_rolled_back(registry):
    promote(registry, 1)
    promote(registry, 2)
    assert registry.rollback() == ("2", "1")
    assert (registry.champion_version(), registry.previous_version()) == ("1", "2")
    assert registry.rollback() == ("1", "2")  # the rollback is reversible


def test_rollback_to_a_named_version(registry):
    for n in (1, 2, 3):
        promote(registry, n)
    assert registry.rollback("1") == ("3", "1")
    assert registry.previous_version() == "3"


def test_rollback_errors(registry):
    with pytest.raises(RegistryError, match="No previous version"):
        registry.rollback()
    promote(registry, 1)
    with pytest.raises(RegistryError, match="does not exist"):
        registry.rollback("9")
    with pytest.raises(RegistryError, match="already the champion"):
        registry.rollback("1")
    assert registry.champion_version() == "1"  # failed rollbacks change nothing
