"""Train -> evaluate -> test -> register on synthetic data, with a real registry."""

import json

import mlflow
import pytest
from src.common.errors import DataValidationError
from src.pipeline import evaluate, register, test_gate, train


@pytest.fixture
def flow_params(params):
    params["promotion"] = {"model_name": "aq-test", "max_ratio_to_baseline": 1.02}
    return params


def run_pipeline(p):
    """Run the four stage functions in order; return register.json."""
    train.run_train(p)
    evaluate.run_evaluate(p)
    test_gate.run_gate(p)
    register.run_register(p)
    reports = p["paths"]["reports_dir"]
    return json.loads(open(f"{reports}/register.json").read())


def test_first_model_is_promoted_then_an_equal_candidate_is_rejected(
    flow_params,
    tracking,
    tmp_path,
):
    first = run_pipeline(flow_params)
    assert first["promoted"] and first["version"] == "1"
    eval1 = json.loads((tmp_path / "reports" / "eval.json").read_text())
    assert eval1["champion"] is None
    assert set(eval1["candidate"]["horizons"]) == {"1h", "24h"}

    # Same data and settings -> the same model: it is not better, so it is rejected.
    second = run_pipeline(flow_params)
    assert not second["promoted"] and second["version"] is None
    eval2 = json.loads((tmp_path / "reports" / "eval.json").read_text())
    assert eval2["champion"]["version"] == "1"
    assert eval2["champion"]["mean_mae"] == pytest.approx(
        eval2["candidate"]["mean_mae"]
    )
    assert "not lower than champion" in second["reasons"][0]

    reg = register.ModelRegistryClient("aq-test")
    assert reg.champion_version() == "1" and len(reg.versions()) == 1
    rejected = mlflow.get_run(second["mlflow_run_id"]).data.tags
    assert rejected["promotion"] == "rejected"
    assert "not lower than champion" in rejected["rejected_reasons"]
    promoted = mlflow.get_run(first["mlflow_run_id"]).data.tags
    assert promoted["promotion"] == "promoted" and promoted["registry_version"] == "1"


def test_promoted_version_carries_tags_and_can_be_loaded_by_alias(
    flow_params,
    tracking,
):
    run_pipeline(flow_params)
    reg = register.ModelRegistryClient("aq-test")
    tags = reg.versions()[0]["tags"]
    assert {"cutoff", "git_commit", "mae_1h", "mae_24h", "model_1h"} <= set(tags)
    assert mlflow.pyfunc.load_model(reg.champion_uri()) is not None


def test_evaluate_scores_the_package_like_the_train_stage(
    flow_params,
    tracking,
    tmp_path,
):
    train.run_train(flow_params)
    evaluate.run_evaluate(flow_params)
    doc = json.loads((tmp_path / "reports" / "eval.json").read_text())
    trained = json.loads((tmp_path / "reports" / "train_metrics.json").read_text())
    for name, h in doc["candidate"]["horizons"].items():
        # the package rounds predictions to 2 decimals, so allow a small gap
        assert h["mae"] == pytest.approx(
            trained["horizons"][name]["chosen"]["mae"], abs=0.01
        )
        assert h["n"] == trained["horizons"][name]["n_eval"]


def test_evaluate_refuses_a_stale_train_report(flow_params, tracking):
    train.run_train(flow_params)
    flow_params["cutoff"] = "2020-02-09 00:00:00"
    with pytest.raises(DataValidationError, match="Run train again"):
        evaluate.run_evaluate(flow_params)


def test_evaluate_and_register_need_their_inputs(flow_params, tracking):
    with pytest.raises(DataValidationError, match="Run train first"):
        evaluate.run_evaluate(flow_params)
    with pytest.raises(DataValidationError, match="Run test first"):
        register.run_register(flow_params)


def test_register_refuses_reports_from_different_runs(flow_params, tracking, tmp_path):
    train.run_train(flow_params)
    evaluate.run_evaluate(flow_params)
    test_gate.run_gate(flow_params)
    gate_path = tmp_path / "reports" / "gate.json"
    gate = json.loads(gate_path.read_text())
    gate["candidate_run_id"] = "someone-else"
    gate_path.write_text(json.dumps(gate))
    with pytest.raises(DataValidationError, match="differ"):
        register.run_register(flow_params)
