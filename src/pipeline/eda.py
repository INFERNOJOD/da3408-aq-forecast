"""Exploratory data analysis (EDA): Spark aggregates saved as small CSV files.

This is not a DVC stage. It is run by hand when the data changes:
    python -m src.pipeline.eda          # writes reports/eda/*.csv
    python scripts/plot_eda.py          # draws docs/img/eda_*.png

Spark does the heavy counting. The results are tiny (a few hundred rows), so
they are collected and written with the csv module and plotted later with
matplotlib. Timestamps are turned into strings inside Spark to avoid the
Python time-zone shift described in docs/PROGRESS.md.
"""

import csv
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as spark_fn

from src.common.config import load_env, load_params
from src.common.logging_setup import configure_logging, get_logger
from src.common.spark import build_spark

log = get_logger(__name__)

BIN_WIDTH = 10
BIN_MAX = 500  # values above this go into the last bin


def pm():
    """Return the PM2.5 column (built lazily: needs an active Spark session)."""
    return spark_fn.col("`PM2.5`")


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    """Write a list of same-keyed dicts as a CSV file (header from first row)."""
    if not rows:
        raise ValueError(f"No rows to write for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    log.info("Wrote %s (%d rows)", path, len(rows))


def _rows(df: DataFrame) -> list[dict[str, Any]]:
    """Collect a small Spark result as plain dicts, rounding floats."""
    out = []
    for row in df.collect():
        out.append(
            {
                k: round(v, 3) if isinstance(v, float) else v
                for k, v in row.asDict().items()
            }
        )
    return out


def missing_by_city_year(city_hour: DataFrame) -> DataFrame:
    """Hourly rows and non-missing PM2.5 per city and year."""
    return (
        city_hour.groupBy("City", spark_fn.year("Datetime").alias("year"))
        .agg(
            spark_fn.count(spark_fn.lit(1)).alias("hours"),
            spark_fn.sum(pm().isNotNull().cast("int")).alias("pm25_present"),
        )
        .orderBy("City", "year")
    )


def coverage_by_city(city_hour: DataFrame) -> DataFrame:
    """First and last PM2.5 reading, hours and PM2.5 count per city."""
    with_pm = spark_fn.when(pm().isNotNull(), spark_fn.col("Datetime"))
    fmt = "yyyy-MM-dd"
    return (
        city_hour.groupBy("City")
        .agg(
            spark_fn.count(spark_fn.lit(1)).alias("hours"),
            spark_fn.sum(pm().isNotNull().cast("int")).alias("pm25_present"),
            spark_fn.date_format(spark_fn.min(with_pm), fmt).alias("first_pm25"),
            spark_fn.date_format(spark_fn.max(with_pm), fmt).alias("last_pm25"),
        )
        .orderBy(spark_fn.desc("pm25_present"))
    )


def seasonality(city_hour: DataFrame, cities: list[str], before: str) -> DataFrame:
    """Mean PM2.5 by hour of day and by month, using only data before ``before``.

    Both profiles are stacked in one table: kind is "hour" or "month".
    """
    base = city_hour.filter(
        spark_fn.col("City").isin(cities)
        & (spark_fn.col("Datetime") < before)
        & pm().isNotNull()
    )
    hourly = (
        base.groupBy("City", spark_fn.hour("Datetime").alias("x"))
        .agg(spark_fn.avg(pm()).alias("mean_pm25"))
        .withColumn("kind", spark_fn.lit("hour"))
    )
    monthly = (
        base.groupBy("City", spark_fn.month("Datetime").alias("x"))
        .agg(spark_fn.avg(pm()).alias("mean_pm25"))
        .withColumn("kind", spark_fn.lit("month"))
    )
    return (
        hourly.unionByName(monthly)
        .select("kind", "City", "x", "mean_pm25")
        .orderBy("kind", "City", "x")
    )


def weekly_series(
    city_hour: DataFrame, cities: list[str], start: str, end: str
) -> DataFrame:
    """Weekly mean PM2.5 per selected city between two dates."""
    return (
        city_hour.filter(
            spark_fn.col("City").isin(cities)
            & (spark_fn.col("Datetime") >= start)
            & (spark_fn.col("Datetime") < end)
            & pm().isNotNull()
        )
        .groupBy(
            "City",
            spark_fn.date_format(
                spark_fn.date_trunc("week", "Datetime"), "yyyy-MM-dd"
            ).alias("week"),
        )
        .agg(
            spark_fn.avg(pm()).alias("mean_pm25"),
            spark_fn.count(spark_fn.lit(1)).alias("n"),
        )
        .orderBy("City", "week")
    )


def period_means(
    city_hour: DataFrame, cities: list[str], periods: dict[str, tuple[str, str]]
) -> DataFrame:
    """Mean PM2.5 per city for named periods (start inclusive, end exclusive)."""
    parts = []
    for name, (start, end) in periods.items():
        parts.append(
            city_hour.filter(
                spark_fn.col("City").isin(cities)
                & (spark_fn.col("Datetime") >= start)
                & (spark_fn.col("Datetime") < end)
                & pm().isNotNull()
            )
            .groupBy("City")
            .agg(
                spark_fn.avg(pm()).alias("mean_pm25"),
                spark_fn.count(spark_fn.lit(1)).alias("n"),
            )
            .withColumn("period", spark_fn.lit(name))
        )
    result = parts[0]
    for part in parts[1:]:
        result = result.unionByName(part)
    return result.select("period", "City", "mean_pm25", "n").orderBy("period", "City")


def histogram(
    city_hour: DataFrame, cities: list[str], periods: dict[str, tuple[str, str]]
) -> DataFrame:
    """Count PM2.5 values in 10-unit bins, per city and period."""
    parts = []
    for name, (start, end) in periods.items():
        binned = spark_fn.least(
            spark_fn.floor(pm() / BIN_WIDTH) * BIN_WIDTH, spark_fn.lit(BIN_MAX)
        ).cast("int")
        parts.append(
            city_hour.filter(
                spark_fn.col("City").isin(cities)
                & (spark_fn.col("Datetime") >= start)
                & (spark_fn.col("Datetime") < end)
                & pm().isNotNull()
            )
            .groupBy("City", binned.alias("bin"))
            .agg(spark_fn.count(spark_fn.lit(1)).alias("n"))
            .withColumn("period", spark_fn.lit(name))
        )
    result = parts[0]
    for part in parts[1:]:
        result = result.unionByName(part)
    return result.select("period", "City", "bin", "n").orderBy("period", "City", "bin")


def quality_flags(city_hour: DataFrame, cities: list[str], ceiling: float) -> DataFrame:
    """Signs of stuck or capped sensors, per selected city.

    same_as_prev: hours whose PM2.5 equals the previous hour exactly.
    zeros: hours with PM2.5 == 0. at_ceiling: hours at the sensor maximum.
    """
    w = Window.partitionBy("City").orderBy("Datetime")
    base = (
        city_hour.filter(spark_fn.col("City").isin(cities))
        .select("City", "Datetime", pm().alias("pm"))
        .withColumn("prev", spark_fn.lag("pm").over(w))
    )
    return (
        base.groupBy("City")
        .agg(
            spark_fn.sum(spark_fn.col("pm").isNotNull().cast("int")).alias("present"),
            spark_fn.sum(
                (spark_fn.col("pm") == spark_fn.col("prev")).cast("int")
            ).alias("same_as_prev"),
            spark_fn.sum((spark_fn.col("pm") == 0).cast("int")).alias("zeros"),
            spark_fn.sum((spark_fn.col("pm") >= ceiling).cast("int")).alias(
                "at_ceiling"
            ),
        )
        .orderBy("City")
    )


def stations_per_year(spark: SparkSession, interim: Path) -> DataFrame:
    """Count stations with PM2.5 readings per city and year (station network)."""
    station_hour = spark.read.parquet(str(interim / "station_hour"))
    stations = spark.read.parquet(str(interim / "stations")).select(
        "StationId", spark_fn.col("City").alias("StationCity")
    )
    return (
        station_hour.filter(pm().isNotNull())
        .join(stations, "StationId", "left")
        .groupBy(
            spark_fn.col("StationCity").alias("City"),
            spark_fn.year("Datetime").alias("year"),
        )
        .agg(spark_fn.countDistinct("StationId").alias("stations"))
        .orderBy("City", "year")
    )


def run_eda(params: dict[str, Any]) -> None:
    """Run every aggregation and write the CSV files under reports/eda/."""
    interim = Path(params["paths"]["interim_dir"])
    out = Path(params["paths"]["reports_dir"]) / "eda"
    cities = params["cities"]
    ceiling = params["validate"]["max_values"]["PM2.5"]
    spark = build_spark("aq-eda", params["spark"])
    try:
        ch = spark.read.parquet(str(interim / "city_hour")).cache()
        write_csv(_rows(missing_by_city_year(ch)), out / "missing_by_city_year.csv")
        write_csv(_rows(coverage_by_city(ch)), out / "coverage_by_city.csv")
        write_csv(_rows(seasonality(ch, cities, "2020-01-01")), out / "seasonality.csv")
        write_csv(
            _rows(weekly_series(ch, cities, "2019-01-01", "2020-07-01")),
            out / "weekly_series.csv",
        )
        # Same calendar windows in 2019 separate the lockdown effect from season.
        periods = {
            "2019_jan_to_mar24": ("2019-01-01", "2019-03-25"),
            "2019_mar25_to_jun": ("2019-03-25", "2019-07-01"),
            "2020_jan_to_mar24": ("2020-01-01", "2020-03-25"),
            "2020_mar25_to_jun": ("2020-03-25", "2020-07-01"),
        }
        write_csv(_rows(period_means(ch, cities, periods)), out / "period_means.csv")
        hist_periods = {
            "before_lockdown": ("2015-01-01", "2020-03-25"),
            "lockdown": ("2020-03-25", "2020-07-01"),
        }
        write_csv(_rows(histogram(ch, cities, hist_periods)), out / "histogram.csv")
        write_csv(_rows(quality_flags(ch, cities, ceiling)), out / "quality_flags.csv")
        write_csv(
            _rows(stations_per_year(spark, interim)), out / "stations_per_year.csv"
        )
    finally:
        spark.stop()


def main() -> None:
    """Command-line entry point."""
    configure_logging()
    load_env()
    run_eda(load_params())


if __name__ == "__main__":
    main()
