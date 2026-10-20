import re
from pathlib import Path

from src.common import schema

LLD = Path(__file__).resolve().parents[1] / "docs" / "LLD.md"


def lld_feature_names():
    """Backticked names in the first column of the LLD section 4 input table."""
    text = LLD.read_text(encoding="utf-8")
    section = text.split("## 4. Model server contract")[1].split("## 5.")[0]
    names = []
    for line in section.splitlines():
        if line.startswith("| `"):
            first_cell = line.split("|")[1]
            names += re.findall(r"`([a-z0-9_]+)`", first_cell)
    return names


def test_features_match_lld_table_in_order():
    assert schema.FEATURES == lld_feature_names()


def test_no_duplicate_columns():
    assert len(schema.FEATURES) == len(set(schema.FEATURES))


def test_stored_columns_are_features_without_horizon():
    assert schema.FEATURES[0] == "horizon_h"
    assert schema.FEATURES[1:] == schema.FEATURE_COLUMNS


def test_targets_follow_horizons():
    assert schema.HORIZONS == {1: "y_1h", 24: "y_24h"}
    assert schema.TARGETS == ["y_1h", "y_24h"]
