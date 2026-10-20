"""Stage 1 of the DVC pipeline: convert raw CSV files to Parquet with Spark.

Why Parquet: it is columnar and compressed, so later stages read only the
columns they need and much faster than from CSV. Types are fixed here once
(explicit schema), so bad values fail early instead of causing silent errors.

Run: ``python -m src.pipeline.ingest``
"""

from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import types as spark_types

from src.common.config import load_env, load_params
from src.common.errors import DataValidationError
from src.common.logging_setup import configure_logging, get_logger
from src.common.spark import build_spark
from src.common.stage_runner import run_stage

log = get_logger(__name__)

POLLUTANTS = [
    "PM2.5",
    "PM10",
    "NO",
    "NO2",
    "NOx",
    "NH3",
    "CO",
    "SO2",
    "O3",
    "Benzene",
    "Toluene",
    "Xylene",
]


def _measurements(
    key: str, time_col: str, time_type: spark_types.DataType
) -> spark_types.StructType:
    """Build the shared 16-column schema used by the four measurement files."""
    fields = [
        spark_types.StructField(key, spark_types.StringType()),
        spark_types.StructField(time_col, time_type),
    ]
    fields += [spark_types.StructField(c, spark_types.DoubleType()) for c in POLLUTANTS]
    fields += [
        spark_types.StructField("AQI", spark_types.DoubleType()),
        spark_types.StructField("AQI_Bucket", spark_types.StringType()),
    ]
    return spark_types.StructType(fields)


# Explicit schemas: names come from here, so the BOM in stations.csv is harmless.
SCHEMAS: dict[str, spark_types.StructType] = {
    "city_day": _measurements("City", "Date", spark_types.DateType()),
    "city_hour": _measurements("City", "Datetime", spark_types.TimestampType()),
    "station_day": _measurements("StationId", "Date", spark_types.DateType()),
    "station_hour": _measurements("StationId", "Datetime", spark_types.TimestampType()),
    "stations": spark_types.StructType(
        [
            spark_types.StructField(c, spark_types.StringType())
            for c in ["StationId", "StationName", "City", "State", "Status"]
        ]
    ),
}


def count_csv_rows(path: Path) -> int:
    """Count data rows (lines minus header) without Spark.

    This is an independent check on Spark: after writing Parquet, row counts
    must match. The raw files have no line breaks inside quoted fields.
    """
    lines = 0
    with path.open("rb") as fh:
        for _ in fh:
            lines += 1
    return max(lines - 1, 0)


def read_csv(
    spark: SparkSession, path: Path, schema: spark_types.StructType
) -> DataFrame:
    """Read one CSV with an explicit schema; FAILFAST stops on malformed rows."""
    return (
        spark.read.option("header", True)
        .option("mode", "FAILFAST")
        .option("timestampFormat", "yyyy-MM-dd HH:mm:ss")
        .option("dateFormat", "yyyy-MM-dd")
        .schema(schema)
        .csv(str(path))
    )


def ingest_table(
    spark: SparkSession, name: str, raw_dir: Path, out_dir: Path
) -> dict[str, int]:
    """Convert one table to Parquet and verify the row count.

    Returns {"rows_in": n_csv_rows, "rows_out": n_parquet_rows}.
    Raises DataValidationError if the files are missing or counts differ.
    """
    if name not in SCHEMAS:
        raise DataValidationError(f"No schema defined for table '{name}'")
    src = raw_dir / f"{name}.csv"
    if not src.is_file():
        raise DataValidationError(f"Raw file not found: {src}")
    dst = out_dir / name
    rows_in = count_csv_rows(src)
    try:
        read_csv(spark, src, SCHEMAS[name]).write.mode("overwrite").parquet(str(dst))
    except Exception as exc:  # Spark raises Py4J/AnalysisException types
        raise DataValidationError(f"Could not convert {src.name}: {exc}") from exc
    rows_out = spark.read.parquet(str(dst)).count()
    if rows_in != rows_out:
        raise DataValidationError(
            f"{name}: CSV has {rows_in} rows but Parquet has {rows_out}"
        )
    log.info("Ingested %s: %d rows", name, rows_out)
    return {"rows_in": rows_in, "rows_out": rows_out}


def ingest_all(params: dict[str, Any]) -> dict[str, int]:
    """Ingest every table listed in params['ingest']['tables'].

    Returns the total rows_in / rows_out across tables.
    """
    raw_dir = Path(params["paths"]["raw_dir"])
    out_dir = Path(params["paths"]["interim_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    spark = build_spark("aq-ingest", params["spark"])
    totals = {"rows_in": 0, "rows_out": 0}
    try:
        for name in params["ingest"]["tables"]:
            res = ingest_table(spark, name, raw_dir, out_dir)
            totals["rows_in"] += res["rows_in"]
            totals["rows_out"] += res["rows_out"]
    finally:
        spark.stop()
    return totals


def main() -> None:
    """Command-line entry point used by dvc.yaml."""
    configure_logging()
    load_env()
    params = load_params()
    run_stage("ingest", lambda: ingest_all(params), params)


if __name__ == "__main__":
    main()
