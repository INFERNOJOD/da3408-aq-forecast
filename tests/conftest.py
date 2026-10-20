"""Shared test fixtures."""

import pytest
from src.common.spark import build_spark


@pytest.fixture(scope="session")
def spark():
    """One small local Spark session shared by all tests (startup is slow)."""
    session = build_spark(
        "aq-tests", {"driver_memory": "512m", "shuffle_partitions": 2, "cores": 2}
    )
    yield session
    session.stop()
