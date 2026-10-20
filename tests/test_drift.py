import numpy as np
import pytest
from src.monitoring import drift


def test_bin_shares_use_edges_le_value():
    shares = drift.bin_shares(np.array([0.0, 1.0, 1.5, 2.0, 9.0]), [1.0, 2.0])
    # bins: [-inf, 1) -> 0.0 ; [1, 2) -> 1.0, 1.5 ; [2, inf) -> 2.0, 9.0
    assert shares.tolist() == [0.2, 0.4, 0.4]


def test_psi_is_zero_for_the_same_distribution():
    rng = np.random.default_rng(0)
    ref = rng.normal(50, 10, 5000)
    edges, props = drift.reference_bins(ref, 10)
    assert drift.psi(ref, edges, props) == pytest.approx(0.0, abs=1e-9)


def test_psi_grows_with_the_shift():
    rng = np.random.default_rng(1)
    edges, props = drift.reference_bins(rng.normal(50, 10, 5000), 10)
    small = drift.psi(rng.normal(52, 10, 168), edges, props)
    large = drift.psi(rng.normal(25, 10, 168), edges, props)
    assert 0 < small < large


def test_psi_with_empty_bins_stays_finite():
    assert np.isfinite(drift.psi(np.array([100.0] * 10), [1.0, 2.0], [0.5, 0.5, 0.0]))


def test_psi_rejects_mismatched_reference():
    with pytest.raises(ValueError, match="proportions"):
        drift.psi(np.array([1.0]), [1.0, 2.0], [0.5, 0.5])


def test_reference_bins_drop_tied_edges():
    edges, props = drift.reference_bins(np.array([5.0] * 50), 10)
    assert edges == [5.0] and props == [0.0, 1.0]
    with pytest.raises(ValueError, match="empty"):
        drift.reference_bins(np.array([]), 10)


def test_loyo_leaves_the_scored_year_out():
    same = np.arange(100, dtype=float)
    by_year = {y: {1: same, 2: same} for y in (2017, 2018, 2019)}
    scores = drift.loyo_psi(by_year, 4, [1, 2], 10)
    assert len(scores) == 6 and max(scores) == pytest.approx(0.0, abs=1e-9)
    by_year[2019] = {1: same + 1000, 2: same}  # one unusual week
    scores = drift.loyo_psi(by_year, 4, [1, 2], 10)
    assert sum(s > 1 for s in scores) >= 1


def test_loyo_skips_small_blocks():
    by_year = {2018: {1: np.ones(5)}, 2019: {1: np.ones(50)}}
    assert drift.loyo_psi(by_year, 4, [1], 10) == []


def test_thresholds_skip_cities_with_too_few_years():
    vals = np.arange(200, dtype=float)
    values = {
        "Delhi": {y: {1: vals + y % 3} for y in (2017, 2018, 2019)},
        "Kolkata": {y: {1: vals} for y in (2018, 2019)},
    }
    out = drift.loyo_thresholds(values, 4, [1], 95, 3, 10)
    assert set(out) == {"Delhi"}
    assert out["Delhi"]["n_values"] == 3 and out["Delhi"]["years"] == [2017, 2018, 2019]


REF = {"edges": [10.0, 20.0, 30.0], "proportions": [0.25, 0.25, 0.25, 0.25]}


def detector(min_cities=2):
    ref = {c: [REF, REF] for c in ("A", "B", "C", "K")}
    return drift.DriftDetector(ref, {"A": 0.5, "B": 0.5, "C": 0.5}, min_cities, 4)


def test_detector_needs_a_full_window():
    d = detector()
    assert d.city_psi("A", np.array([5.0] * 4), 2) is None  # hour 2 < window - 1
    assert d.city_psi("A", np.array([5.0, np.nan, np.nan, np.nan]), 3) is None
    assert d.city_psi("A", np.array([5.0] * 4), 3) > 0.5


def test_detector_uses_the_block_of_the_last_hour_and_caps_it():
    d = detector()
    assert d.block_of(3) == 0 and d.block_of(4) == 1 and d.block_of(99) == 1


def test_rule_counts_only_voting_cities():
    d = detector(min_cities=2)
    shifted, normal = np.array([5.0] * 4), np.array([5.0, 15.0, 25.0, 35.0])
    out = d.evaluate({"A": shifted, "B": normal, "K": shifted}, 3)
    assert out["cities_exceeding"] == 1 and out["exceeding"] == ["A"]
    assert out["any_drift"] is False
    k = next(c for c in out["cities"] if c["city"] == "K")
    assert k["votes"] is False and k["exceeds"] is None and k["psi"] > 0.5
    out = d.evaluate({"A": shifted, "B": shifted, "C": normal}, 3)
    assert out["psi_condition"] is True and out["any_drift"] is True


def test_rule_before_the_window_is_full():
    out = detector().evaluate({"A": np.array([5.0] * 4)}, 0)
    assert out["cities"][0]["psi"] is None and out["any_drift"] is False
