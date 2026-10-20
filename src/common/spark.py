"""Create the local Spark session with the project's memory limits."""

from typing import Any

from pyspark.sql import SparkSession

from src.common.logging_setup import get_logger

log = get_logger(__name__)


def build_spark(
    app_name: str, spark_params: dict[str, Any] | None = None
) -> SparkSession:
    """Return a local-mode SparkSession configured from params.yaml['spark'].

    Memory is capped (default driver 2g) because the VM has only 8 GB RAM.
    Session time zone is UTC so timestamps keep the wall-clock values found in
    the CSV files (the data is in IST and we never convert it).
    """
    p = {"driver_memory": "2g", "shuffle_partitions": 8, "cores": 4}
    p.update(spark_params or {})
    spark = (
        SparkSession.builder.master(f"local[{p['cores']}]")
        .appName(app_name)
        .config("spark.driver.memory", p["driver_memory"])
        .config("spark.sql.shuffle.partitions", str(p["shuffle_partitions"]))
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    log.info(
        "Spark %s started (driver=%s, shuffle_partitions=%s)",
        spark.version,
        p["driver_memory"],
        p["shuffle_partitions"],
    )
    return spark
