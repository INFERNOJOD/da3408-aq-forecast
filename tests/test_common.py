import logging

import pytest
from src.common import config, logging_setup
from src.common.errors import AQError, ConfigError, PipelineStageError


def test_load_params_ok(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("a: 1\nb: [x, y]\n")
    assert config.load_params(p) == {"a": 1, "b": ["x", "y"]}


def test_load_params_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        config.load_params(tmp_path / "nope.yaml")


def test_load_params_bad_yaml(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("a: [unclosed\n")
    with pytest.raises(ConfigError):
        config.load_params(p)


def test_load_params_not_mapping(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("- 1\n- 2\n")
    with pytest.raises(ConfigError):
        config.load_params(p)


def test_real_params_file_is_valid():
    params = config.load_params()
    assert params["spark"]["driver_memory"] == "2g"
    assert params["spark"]["shuffle_partitions"] == 8
    assert len(params["cities"]) == 7


def test_require_env(monkeypatch):
    monkeypatch.setenv("AQ_TEST_VAR", "v")
    assert config.require_env("AQ_TEST_VAR") == "v"
    monkeypatch.delenv("AQ_TEST_VAR")
    with pytest.raises(ConfigError):
        config.require_env("AQ_TEST_VAR")


def test_load_env_does_not_override(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("AQ_X=fromfile\nAQ_Y=fromfile\n")
    monkeypatch.setenv("AQ_X", "real")
    monkeypatch.delenv("AQ_Y", raising=False)
    config.load_env(f)
    import os

    assert os.environ["AQ_X"] == "real"
    assert os.environ["AQ_Y"] == "fromfile"
    monkeypatch.delenv("AQ_Y")


def test_load_env_missing_file_is_ok(tmp_path):
    config.load_env(tmp_path / "absent.env")


def test_configure_logging_levels(monkeypatch):
    logging_setup.configure_logging("debug")
    assert logging.getLogger().level == logging.DEBUG
    logging_setup.configure_logging("not-a-level")
    assert logging.getLogger().level == logging.INFO
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    logging_setup.configure_logging()
    assert logging.getLogger().level == logging.WARNING


def test_pipeline_stage_error():
    err = PipelineStageError("ingest", "boom")
    assert isinstance(err, AQError)
    assert err.stage == "ingest"
    assert "ingest" in str(err) and "boom" in str(err)
