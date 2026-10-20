"""PSI drift detection for ``pm25_lag_1`` (docs/HLD.md, "Drift detection").

One module is used in three places, so the rule cannot differ between them:

- the features stage computes the per-city thresholds (``loyo_thresholds``),
- the backend scores the live replay window (``DriftDetector``),
- ``scripts/replay.py`` replays whole years offline for the acceptance test.

The rule: a city *exceeds* when the PSI of its last 168 hours against the
same-season reference block is above its own threshold. Drift is declared when
at least ``min_cities`` voting cities exceed in the same hour. The threshold of a
city is a high percentile of its PSI in normal weeks, where each week of each
reference year is compared with the same block of the other years
(leave-one-year-out). A city with too few reference years gets no threshold and
does not vote.

The rolling MAE ratio is not part of the rule. In Stage 11 I measured that the
model's error is lower during the lockdown than in normal springs, because the
error grows with the PM2.5 level (docs/metrics.md). It is still reported.
"""

from collections.abc import Mapping, Sequence

import numpy as np

EPS = 1e-4  # floor for empty bins, so log(q / p) stays finite
MIN_WINDOW_SHARE = 0.5  # a live window needs at least this share of non-null values


def bin_shares(values: np.ndarray, edges: Sequence[float]) -> np.ndarray:
    """Share of ``values`` in each bin. Bin index = number of edges e <= value."""
    idx = np.searchsorted(np.asarray(edges, dtype=float), values, side="right")
    counts = np.bincount(idx, minlength=len(edges) + 1)
    return counts / max(len(values), 1)


def psi(
    values: np.ndarray, edges: Sequence[float], proportions: Sequence[float]
) -> float:
    """Return the population stability index of ``values`` against a reference."""
    q = np.maximum(bin_shares(np.asarray(values, dtype=float), edges), EPS)
    p = np.maximum(np.asarray(proportions, dtype=float), EPS)
    if len(p) != len(q):
        raise ValueError(f"{len(edges)} edges need {len(q)} proportions, got {len(p)}")
    return float(np.sum((q - p) * np.log(q / p)))


def reference_bins(values: np.ndarray, n_bins: int) -> tuple[list[float], list[float]]:
    """Decile-style edges and bin shares of a reference sample.

    The edges are the 1/n, 2/n, ... quantiles, taken as actual sample values
    (like Spark's ``percentile_approx``), with ties removed.
    """
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        raise ValueError("reference sample is empty")
    qs = [i / n_bins for i in range(1, n_bins)]
    edges = sorted(set(np.quantile(values, qs, method="inverted_cdf").tolist()))
    return edges, bin_shares(values, edges).tolist()


def loyo_psi(
    blocks_by_year: Mapping[int, Mapping[int, np.ndarray]],
    n_bins: int,
    blocks: Sequence[int],
    min_n: int,
) -> list[float]:
    """PSI of every (year, block) against the same block of the other years.

    ``blocks_by_year[year][block]`` holds the values of one city. A block with
    fewer than ``min_n`` values, on either side, is skipped.
    """
    out = []
    for year, by_block in blocks_by_year.items():
        for block in blocks:
            live = by_block.get(block)
            if live is None or len(live) < min_n:
                continue
            others = [
                v[block] for y, v in blocks_by_year.items() if y != year and block in v
            ]
            ref = np.concatenate(others) if others else np.array([])
            if len(ref) < min_n:
                continue
            out.append(psi(live, *reference_bins(ref, n_bins)))
    return out


def loyo_thresholds(
    values: Mapping[str, Mapping[int, Mapping[int, np.ndarray]]],
    n_bins: int,
    blocks: Sequence[int],
    percentile: float,
    min_years: int,
    min_n: int,
) -> dict[str, dict]:
    """Per-city PSI threshold from normal weeks (leave-one-year-out).

    ``values[city][year][block]`` are the reference values. Cities with fewer
    than ``min_years`` years are left out, so they do not vote.
    """
    out = {}
    for city, by_year in values.items():
        if len(by_year) < min_years:
            continue
        scores = loyo_psi(by_year, n_bins, blocks, min_n)
        if not scores:
            continue
        out[city] = {
            "psi_threshold": round(float(np.percentile(scores, percentile)), 4),
            "n_values": len(scores),
            "years": sorted(by_year),
        }
    return out


class DriftDetector:
    """Scores live windows against the reference and applies the rule."""

    def __init__(
        self,
        reference: Mapping[str, Sequence[Mapping]],
        thresholds: Mapping[str, float],
        min_cities: int,
        window_h: int = 168,
    ) -> None:
        """Keep the reference blocks per city and the per-city thresholds.

        ``reference[city]`` is the list of blocks from baseline_stats.json, each
        with ``edges`` and ``proportions``. ``thresholds`` holds only the
        voting cities.
        """
        self.reference = {c: list(blocks) for c, blocks in reference.items()}
        self.thresholds = dict(thresholds)
        self.min_cities = min_cities
        self.window_h = window_h

    def block_of(self, replay_hour: int) -> int:
        """Return the reference block of a window ending at ``replay_hour``."""
        n_blocks = max((len(b) for b in self.reference.values()), default=1)
        return min(replay_hour // self.window_h, n_blocks - 1)

    def city_psi(self, city: str, window: np.ndarray, replay_hour: int) -> float | None:
        """PSI of one city's window, or None if it cannot be scored yet."""
        blocks = self.reference.get(city)
        if not blocks or replay_hour < self.window_h - 1:
            return None
        values = np.asarray(window, dtype=float)
        values = values[~np.isnan(values)]
        if len(values) < MIN_WINDOW_SHARE * self.window_h:
            return None
        block = blocks[min(self.block_of(replay_hour), len(blocks) - 1)]
        return psi(values, block["edges"], block["proportions"])

    def evaluate(self, windows: Mapping[str, np.ndarray], replay_hour: int) -> dict:
        """Score every city and apply the rule for one replay hour."""
        cities = []
        exceeding = []
        for city, window in windows.items():
            score = self.city_psi(city, window, replay_hour)
            threshold = self.thresholds.get(city)
            exceeds = None
            if score is not None and threshold is not None:
                exceeds = score > threshold
                if exceeds:
                    exceeding.append(city)
            cities.append(
                {
                    "city": city,
                    "psi": None if score is None else round(score, 4),
                    "psi_threshold": threshold,
                    "exceeds": exceeds,
                    "votes": threshold is not None,
                }
            )
        condition = len(exceeding) >= self.min_cities
        return {
            "reference_block": self.block_of(max(replay_hour, 0)),
            "cities": cities,
            "exceeding": exceeding,
            "cities_exceeding": len(exceeding),
            "psi_condition": condition,
            "any_drift": condition,
        }
