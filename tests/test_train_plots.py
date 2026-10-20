import numpy as np
import pandas as pd
from src.pipeline import train_plots


def test_plots_are_written(tmp_path):
    imp = {
        1: pd.Series({"a": 5.0, "b": 3.0, "c": 1.0}),
        24: pd.Series({"a": 1.0, "b": 2.0, "c": 7.0}),
    }
    p1 = train_plots.plot_feature_importance(imp, tmp_path / "fi.png")
    rng = np.random.default_rng(0)
    p2 = train_plots.plot_residuals(
        {1: rng.normal(0, 3, 200), 24: rng.normal(1, 8, 200)}, tmp_path / "res.png"
    )
    for p in (p1, p2):
        assert (
            p.exists() and p.read_bytes()[:4] == b"\x89PNG" and p.stat().st_size > 5000
        )
