from pathlib import Path

import pytest
from scripts import plot_eda

CSV_DIR = Path(__file__).resolve().parents[1] / "reports" / "eda"


@pytest.mark.skipif(not CSV_DIR.is_dir(), reason="EDA CSV files not generated")
def test_all_figures_are_drawn(tmp_path):
    paths = plot_eda.main(str(CSV_DIR), str(tmp_path))
    assert len(paths) == 6
    for p in paths:
        assert p.exists() and p.stat().st_size > 10_000
        assert p.read_bytes()[:4] == b"\x89PNG"
