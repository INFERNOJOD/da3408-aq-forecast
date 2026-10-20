import json

import pytest
from src.common.errors import DataValidationError
from src.pipeline import test_gate as gate_stage


def eval_doc(cand_1h=4.0, cand_24h=10.0, base_1h=5.0, base_24h=10.0, champion=None):
    """An eval.json with chosen-model MAEs and best-baseline MAEs per horizon."""
    horizons = {
        "1h": {"mae": cand_1h, "model": "lightgbm"},
        "24h": {"mae": cand_24h, "model": "ridge"},
    }
    baselines = {"1h": base_1h, "24h": base_24h}
    for name, h in horizons.items():
        h["best_baseline"] = {"name": "persistence", "mae": baselines[name]}
    return {
        "candidate": {
            "run_id": "r1",
            "mean_mae": (cand_1h + cand_24h) / 2,
            "horizons": horizons,
        },
        "champion": champion,
    }


def champion(mean_mae):
    return {"version": "3", "mean_mae": mean_mae, "horizons": {}}


def test_first_model_passes_when_within_the_baseline_limit():
    gate = gate_stage.decide(eval_doc(), 1.02)
    assert gate["passed"] and gate["first_model"] and gate["reasons"] == []


def test_limit_is_inclusive_and_not_relaxed_for_the_first_model():
    assert gate_stage.decide(eval_doc(cand_24h=10.2, base_24h=10.0), 1.02)["passed"]
    gate = gate_stage.decide(eval_doc(cand_24h=10.3, base_24h=10.0), 1.02)
    assert not gate["passed"] and gate["first_model"]
    assert "24h" in gate["reasons"][0] and "1.03" in gate["reasons"][0]


def test_candidate_must_beat_the_champion_strictly():
    assert gate_stage.decide(eval_doc(champion=champion(8.0)), 1.02)["passed"]
    tie = gate_stage.decide(eval_doc(champion=champion(7.0)), 1.02)
    assert not tie["passed"] and "not lower than champion v3" in tie["reasons"][0]
    worse = gate_stage.decide(eval_doc(champion=champion(6.0)), 1.02)
    assert not worse["passed"] and not worse["first_model"]


def test_both_reasons_are_reported():
    gate = gate_stage.decide(
        eval_doc(cand_1h=9.0, base_1h=5.0, champion=champion(1.0)), 1.02
    )
    assert len(gate["reasons"]) == 2


def test_run_gate_writes_gate_json_and_a_rejection_is_not_a_failure(tmp_path):
    params = {
        "paths": {"reports_dir": str(tmp_path)},
        "promotion": {"max_ratio_to_baseline": 1.02},
    }
    (tmp_path / "eval.json").write_text(json.dumps(eval_doc(cand_1h=9.0)))
    gate_stage.run_gate(params)  # does not raise
    assert json.loads((tmp_path / "gate.json").read_text())["passed"] is False


def test_run_gate_needs_eval_json(tmp_path):
    params = {
        "paths": {"reports_dir": str(tmp_path)},
        "promotion": {"max_ratio_to_baseline": 1.02},
    }
    with pytest.raises(DataValidationError, match="Run evaluate first"):
        gate_stage.run_gate(params)
