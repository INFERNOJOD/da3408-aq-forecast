"""Stage 3 of the DVC pipeline: build model features and targets with Spark.

Output (see docs/LLD.md, sections 4, 6 and 7):
  data/features/train.parquet    hours up to the cutoff, features + targets
  data/features/serving.parquet  hours of the live replay, features + actuals
  reports/baseline_stats.json    drift baseline for pm25_lag_1 (PSI bins)

Features only run after validate has passed (see require_validation_passed).

Design rules I follow here:
  * Every feature at hour t uses only data from hour t and earlier (no leaks).
  * Lags are counted in hours, not rows. I first build a complete hourly grid
    per city so a missing hour never shifts the lags.
  * Gaps are forward-filled for at most ``max_ffill_hours`` and only for the
    inputs. Targets are never filled. A missing target stays null.
  * Training rows never contain a target from after the cutoff.

The transforms are functions ``DataFrame -> DataFrame``. Only ``run_features``
touches the disk.

Run: ``python -m src.pipeline.features``
"""

import json
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as spark_fn

from src.common.config import load_env, load_params
from src.common.errors import DataValidationError
from src.common.logging_setup import configure_logging, get_logger
from src.common.schema import (
    ACTUAL_COLUMN,
    CO_POLLUTANT_FEATURES,
    FEATURE_COLUMNS,
    HORIZONS,
    PM25_LAGS,
    ROLL_MEAN_WINDOWS,
    ROLL_STD_WINDOWS,
)
from src.common.spark import build_spark
from src.common.stage_runner import run_stage

log = get_logger(__name__)

# Columns of city_hour used by this stage.
INPUT_COLUMNS = ["City", "Datetime", "PM2.5", *CO_POLLUTANT_FEATURES]
# Temporary column names inside this stage (dots are awkward in Spark).
FILLED = {"PM2.5": "pm25_ff", **{c: f"{c.lower()}_ff" for c in CO_POLLUTANT_FEATURES}}


def select_city_hours(city_hour: DataFrame, cities: list[str]) -> DataFrame:
    """Keep the selected cities and the columns this stage needs."""
    return city_hour.filter(spark_fn.col("City").isin(cities)).select(
        *[spark_fn.col(f"`{c}`") for c in INPUT_COLUMNS]
    )


def complete_hourly_grid(df: DataFrame) -> DataFrame:
    """Return one row per city and hour between the city's first and last hour.

    Hours that are missing in the source get null measurements. This makes
    "24 rows back" mean exactly "24 hours back".
    """
    bounds = df.groupBy("City").agg(
        spark_fn.min("Datetime").alias("t0"), spark_fn.max("Datetime").alias("t1")
    )
    grid = bounds.select(
        "City",
        spark_fn.explode(
            spark_fn.sequence("t0", "t1", spark_fn.expr("interval 1 hour"))
        ).alias("Datetime"),
    )
    return grid.join(df, ["City", "Datetime"], "left")


def _city_window(start: int | None = None, end: int = 0) -> Window:
    """Window over one city's hours in time order, rows relative to the current."""
    w = Window.partitionBy("City").orderBy("Datetime")
    if start is None:
        return w
    return w.rowsBetween(start, end)


def add_forward_filled(df: DataFrame, max_gap: int) -> DataFrame:
    """Add *_ff columns: the last seen value, carried over gaps up to ``max_gap`` hours.

    The window covers the current hour and the ``max_gap`` hours before it, so a
    gap of ``max_gap`` missing hours is filled and a longer gap is left null.
    """
    w = _city_window(-max_gap, 0)
    for source, target in FILLED.items():
        df = df.withColumn(
            target, spark_fn.last(spark_fn.col(f"`{source}`"), ignorenulls=True).over(w)
        )
    return df


def add_calendar_features(df: DataFrame, cities: list[str]) -> DataFrame:
    """Add city_code, hour, dow (Monday=0), month and is_weekend of hour t."""
    mapping = spark_fn.create_map(
        *[x for i, c in enumerate(cities) for x in (spark_fn.lit(c), spark_fn.lit(i))]
    )
    dow = (spark_fn.dayofweek("Datetime") + 5) % 7  # Spark: Sunday=1 -> Monday=0
    return (
        df.withColumn("city_code", mapping[spark_fn.col("City")].cast("int"))
        .withColumn("hour", spark_fn.hour("Datetime"))
        .withColumn("dow", dow.cast("int"))
        .withColumn("month", spark_fn.month("Datetime"))
        .withColumn("is_weekend", (spark_fn.col("dow") >= 5).cast("int"))
    )


def add_lag_features(df: DataFrame) -> DataFrame:
    """Add PM2.5 lags, rolling mean/std, and current-hour co-pollutants.

    All of them look backwards only (lag k = k-1 hours before t, windows end at t).
    """
    w = _city_window()
    for k in PM25_LAGS:
        df = df.withColumn(f"pm25_lag_{k}", spark_fn.lag("pm25_ff", k - 1).over(w))
    for n in ROLL_MEAN_WINDOWS:
        df = df.withColumn(
            f"pm25_roll_mean_{n}", spark_fn.avg("pm25_ff").over(_city_window(-(n - 1)))
        )
    for n in ROLL_STD_WINDOWS:
        df = df.withColumn(
            f"pm25_roll_std_{n}",
            spark_fn.stddev("pm25_ff").over(_city_window(-(n - 1))),
        )
    for source, name in CO_POLLUTANT_FEATURES.items():
        df = df.withColumn(name, spark_fn.col(FILLED[source]))
    return df


def add_targets(df: DataFrame) -> DataFrame:
    """Add the observed PM2.5 at t (``pm25``) and the targets y_1h, y_24h.

    A target is the raw observed value h hours later (``lead``), never filled.
    """
    w = _city_window()
    df = df.withColumn(ACTUAL_COLUMN, spark_fn.col("`PM2.5`"))
    for horizon, name in HORIZONS.items():
        df = df.withColumn(name, spark_fn.lead(ACTUAL_COLUMN, horizon).over(w))
    return df


def build_features(city_hour: DataFrame, cities: list[str], max_gap: int) -> DataFrame:
    """Turn raw hourly rows into one feature row per selected city and hour.

    Columns: City, Datetime, FEATURE_COLUMNS, pm25, y_1h, y_24h.
    """
    df = complete_hourly_grid(select_city_hours(city_hour, cities))
    df = add_forward_filled(df, max_gap)
    df = add_calendar_features(df, cities)
    df = add_lag_features(df)
    df = add_targets(df)
    return df.select(
        "City", "Datetime", *FEATURE_COLUMNS, ACTUAL_COLUMN, *HORIZONS.values()
    )


def make_train_set(df: DataFrame, cutoff: str) -> DataFrame:
    """Keep hours up to the cutoff and hide targets that fall after it.

    A row at hour t with horizon h only gets its target if t + h <= cutoff.
    Otherwise the target is set to null, so training can never see the future.
    """
    rows = df.filter(spark_fn.col("Datetime") <= spark_fn.lit(cutoff).cast("timestamp"))
    for horizon, name in HORIZONS.items():
        target_time = spark_fn.col("Datetime") + spark_fn.expr(
            f"interval {horizon} hours"
        )
        rows = rows.withColumn(
            name,
            spark_fn.when(
                target_time <= spark_fn.lit(cutoff).cast("timestamp"),
                spark_fn.col(name),
            ),
        )
    return rows


def make_serving_set(df: DataFrame, start: str, end: str) -> DataFrame:
    """Keep the hours of the live replay (start and end inclusive).

    Features are causal, so they can be used as they are. The actuals stay in
    the table: the backend reveals them only when its replay clock passes them.
    """
    return df.filter(
        (spark_fn.col("Datetime") >= spark_fn.lit(start).cast("timestamp"))
        & (spark_fn.col("Datetime") <= spark_fn.lit(end).cast("timestamp"))
    )


def baseline_stats(train: DataFrame, cities: list[str], n_bins: int) -> dict[str, Any]:
    """Describe pm25_lag_1 per city on the training rows, for PSI drift checks.

    Bin edges are the quantiles 1/n, 2/n, ... of the training values. Bin index
    of a value x is the number of edges e with e <= x, so bins are
    [-inf, e1), [e1, e2), ..., [e_last, +inf). Stage 11 uses the same rule on
    live data, so the proportions here are directly comparable.
    """
    quantiles = [i / n_bins for i in range(1, n_bins)]
    out: dict[str, Any] = {}
    for city in cities:
        values = train.filter(
            (spark_fn.col("City") == city) & spark_fn.col("pm25_lag_1").isNotNull()
        ).select(spark_fn.col("pm25_lag_1").alias("x"))
        n = values.count()
        if n == 0:
            raise DataValidationError(f"No pm25_lag_1 values for {city} in training")
        raw_edges = values.stat.approxQuantile("x", quantiles, 0.001)
        edges = sorted(set(raw_edges))  # drop duplicate edges from tied values
        index = sum((spark_fn.col("x") >= spark_fn.lit(e)).cast("int") for e in edges)
        counts = {
            r["bin"]: r["n"]
            for r in values.groupBy(index.alias("bin"))
            .agg(spark_fn.count(spark_fn.lit(1)).alias("n"))
            .collect()
        }
        stats = values.agg(
            spark_fn.avg("x").alias("mean"),
            spark_fn.stddev("x").alias("std"),
            spark_fn.min("x").alias("min"),
            spark_fn.max("x").alias("max"),
        ).collect()[0]
        out[city] = {
            "n": n,
            "edges": [round(e, 4) for e in edges],
            "proportions": [
                round(counts.get(i, 0) / n, 6) for i in range(len(edges) + 1)
            ],
            "mean": round(stats["mean"], 4),
            "std": round(stats["std"], 4),
            "min": stats["min"],
            "max": stats["max"],
        }
    return out


def require_validation_passed(reports_dir: Path) -> None:
    """Stop unless the validate stage ran and passed.

    The DVC graph already orders validate before features. This check also
    protects a direct ``python -m src.pipeline.features`` run, so features are
    never built from data that failed validation.
    """
    report = reports_dir / "validation.json"
    try:
        status = json.loads(report.read_text(encoding="utf-8")).get("status")
    except FileNotFoundError as exc:
        raise DataValidationError(
            f"{report} not found: run the validate stage first"
        ) from exc
    except json.JSONDecodeError as exc:
        raise DataValidationError(f"{report} is not valid JSON") from exc
    if status != "passed":
        raise DataValidationError(f"Validation status is '{status}', not 'passed'")


def run_features(params: dict[str, Any]) -> dict[str, int]:
    """Build and write all feature files. Returns rows_in and rows_out."""
    require_validation_passed(Path(params["paths"]["reports_dir"]))
    interim = Path(params["paths"]["interim_dir"])
    out_dir = Path(params["paths"]["features_dir"])
    reports = Path(params["paths"]["reports_dir"])
    cities = params["cities"]
    cutoff = params["cutoff"]
    fp = params["features"]
    spark = build_spark("aq-features", params["spark"])
    try:
        city_hour = spark.read.parquet(str(interim / "city_hour"))
        rows_in = select_city_hours(city_hour, cities).count()
        feats = build_features(city_hour, cities, fp["max_ffill_hours"]).cache()

        train = make_train_set(feats, cutoff)
        serving = make_serving_set(feats, fp["serving_start"], params["replay"]["end"])
        out_dir.mkdir(parents=True, exist_ok=True)
        train.write.mode("overwrite").parquet(str(out_dir / "train.parquet"))
        serving.coalesce(1).write.mode("overwrite").parquet(
            str(out_dir / "serving.parquet")
        )
        n_train = spark.read.parquet(str(out_dir / "train.parquet")).count()
        n_serving = spark.read.parquet(str(out_dir / "serving.parquet")).count()
        log.info("Wrote %d training rows and %d serving rows", n_train, n_serving)

        stats = baseline_stats(
            spark.read.parquet(str(out_dir / "train.parquet")),
            cities,
            fp["psi_bins"],
        )
    finally:
        spark.stop()

    reports.mkdir(parents=True, exist_ok=True)
    doc = {
        "feature": "pm25_lag_1",
        "cutoff": cutoff,
        "n_bins": fp["psi_bins"],
        "bin_rule": "bin index = number of edges e with e <= value",
        "cities": stats,
    }
    (reports / "baseline_stats.json").write_text(
        json.dumps(doc, indent=2), encoding="utf-8"
    )
    return {"rows_in": rows_in, "rows_out": n_train + n_serving}


def main() -> None:
    """Command-line entry point used by dvc.yaml."""
    configure_logging()
    load_env()
    params = load_params()
    run_stage("features", lambda: run_features(params), params)


if __name__ == "__main__":
    main()
