"""Stage 3 of the DVC pipeline: build model features and targets with Spark.

Output (see docs/LLD.md, sections 4, 6 and 7):
  data/features/train.parquet    hours up to the cutoff, features + targets
  data/features/serving.parquet  hours of the live replay, features + actuals
  reports/baseline_stats.json    same-season drift baseline for pm25_lag_1 (PSI bins)
  reports/drift_thresholds.json  per-city PSI threshold from normal weeks (Stage 11)

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
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
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
from src.monitoring.drift import loyo_thresholds

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


def replay_hours(replay: dict[str, str]) -> int:
    """Count the hours in the replay window, start and end both included."""
    start = datetime.fromisoformat(replay["start"])
    end = datetime.fromisoformat(replay["end"])
    return int((end - start).total_seconds() // 3600) + 1


def reference_frame(
    df: DataFrame,
    cities: list[str],
    replay: dict[str, str],
    years: list[int],
    week_hours: int,
) -> DataFrame:
    """Rows (City, week, x, year): pm25_lag_1 at the replay's calendar hours.

    ``week`` is the block of ``week_hours`` hours the hour falls in, counted from
    the replay start's month and day in that year. Only ``years`` (both ends
    included) and non-null values are kept.
    """
    start = datetime.fromisoformat(replay["start"])
    n_hours = replay_hours(replay)
    anchor = spark_fn.expr(
        f"make_timestamp(year(Datetime), {start.month}, {start.day}, "
        f"{start.hour}, {start.minute}, {start.second})"
    )
    replay_hour = (
        (spark_fn.col("Datetime").cast("long") - anchor.cast("long")) / 3600
    ).cast("int")
    return (
        df.filter(
            spark_fn.col("City").isin(cities)
            & spark_fn.col("pm25_lag_1").isNotNull()
            & spark_fn.year("Datetime").between(years[0], years[1])
        )
        .withColumn("x", spark_fn.col("pm25_lag_1"))
        .withColumn("rh", replay_hour)
        .filter((spark_fn.col("rh") >= 0) & (spark_fn.col("rh") < n_hours))
        .withColumn("week", (spark_fn.col("rh") / week_hours).cast("int"))
        .select("City", "week", "x", spark_fn.year("Datetime").alias("year"))
    )


def baseline_stats(
    df: DataFrame,
    cities: list[str],
    replay: dict[str, str],
    years: list[int],
    n_bins: int,
    week_hours: int,
    min_n: int,
) -> dict[str, Any]:
    """Describe pm25_lag_1 in the same season of earlier years, for PSI drift checks.

    The live replay covers a few calendar months. Comparing it with all seasons
    mixed would flag the normal change of season as drift. So the reference for
    each block of ``week_hours`` hours of the replay is the same hours of the
    calendar in earlier years (``years``, both ends included). Years are aligned
    on the replay start's month and day, so leap years do not shift the blocks.

    For each city and block, bin edges are the quantiles 1/n, 2/n, ... of the
    reference values. The bin index of a value x is the number of edges e with
    e <= x, so bins are [-inf, e1), [e1, e2), ..., [e_last, +inf). Stage 11 uses
    the same rule on live data.
    """
    n_weeks = -(-replay_hours(replay) // week_hours)  # ceiling division
    base = reference_frame(df, cities, replay, years, week_hours).cache()

    quantiles = ", ".join(str(i / n_bins) for i in range(1, n_bins))
    raw = (
        base.groupBy("City", "week")
        .agg(
            spark_fn.expr(f"percentile_approx(x, array({quantiles}), 10000)").alias(
                "raw_edges"
            ),
        )
        .collect()
    )
    # Drop duplicate edges caused by tied values, then use these exact edges.
    edge_rows = [(r["City"], r["week"], sorted(set(r["raw_edges"]))) for r in raw]
    edges_df = base.sparkSession.createDataFrame(
        edge_rows, "City string, week int, edges array<double>"
    )
    binned = base.join(edges_df, ["City", "week"]).withColumn(
        "bin",
        spark_fn.size(spark_fn.filter("edges", lambda e: e <= spark_fn.col("x"))),
    )
    counts = {
        (r["City"], r["week"], r["bin"]): r["n"]
        for r in binned.groupBy("City", "week", "bin")
        .agg(spark_fn.count(spark_fn.lit(1)).alias("n"))
        .collect()
    }
    years_used = {
        r["City"]: sorted(r["ys"])
        for r in base.groupBy("City")
        .agg(spark_fn.collect_set("year").alias("ys"))
        .collect()
    }
    edges_by_key = {(c, w): e for c, w, e in edge_rows}

    out: dict[str, Any] = {}
    problems = []
    for city in cities:
        weeks = []
        for week in range(n_weeks):
            edges = edges_by_key.get((city, week))
            if edges is None:
                problems.append(f"{city} week {week}: no reference values")
                continue
            per_bin = [counts.get((city, week, i), 0) for i in range(len(edges) + 1)]
            n = sum(per_bin)
            if n < min_n:
                problems.append(f"{city} week {week}: only {n} reference values")
            weeks.append(
                {
                    "week": week,
                    "n": n,
                    "edges": [round(e, 4) for e in edges],
                    "proportions": [round(c / n, 6) for c in per_bin] if n else [],
                }
            )
        out[city] = {"years": years_used.get(city, []), "weeks": weeks}
    base.unpersist()
    if problems:
        raise DataValidationError(
            f"Drift baseline needs at least {min_n} values per city and week: "
            + "; ".join(problems[:5])
        )
    return out


def drift_thresholds(
    df: DataFrame,
    cities: list[str],
    replay: dict[str, str],
    years: list[int],
    fp: dict[str, Any],
) -> dict[str, Any]:
    """Per-city PSI thresholds from normal weeks (leave-one-year-out).

    Spark selects the reference values (a few tens of thousands of numbers);
    the PSI itself is computed in ``src.monitoring.drift``, the same code the
    backend uses on live data. Blocks ``threshold_blocks`` (default 1 to 13)
    of every reference year are compared with the same block of the other
    years, and the threshold is the ``threshold_percentile`` of those values.
    """
    week_hours = fp["drift_window_hours"]
    rows = reference_frame(df, cities, replay, years, week_hours).collect()
    grouped: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in rows:
        grouped[r["City"]][r["year"]][r["week"]].append(r["x"])
    values = {
        city: {
            year: {week: np.asarray(v) for week, v in by_week.items()}
            for year, by_week in by_year.items()
        }
        for city, by_year in grouped.items()
    }
    first, last = fp["threshold_blocks"]
    found = loyo_thresholds(
        values,
        fp["psi_bins"],
        range(first, last + 1),
        fp["threshold_percentile"],
        fp["threshold_min_years"],
        fp["baseline_min_n"],
    )
    for city in cities:
        if city not in found:
            log.warning("%s has no PSI threshold and will not vote", city)
    return found


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
    replay_year = int(params["replay"]["start"][:4])
    if fp["baseline_years"][1] >= replay_year:
        raise DataValidationError(
            f"baseline_years {fp['baseline_years']} must end before the replay "
            f"year {replay_year}, or the baseline would contain the replay itself"
        )
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
            params["replay"],
            fp["baseline_years"],
            fp["psi_bins"],
            fp["drift_window_hours"],
            fp["baseline_min_n"],
        )
        thresholds = drift_thresholds(
            spark.read.parquet(str(out_dir / "train.parquet")),
            cities,
            params["replay"],
            fp["baseline_years"],
            fp,
        )
    finally:
        spark.stop()

    reports.mkdir(parents=True, exist_ok=True)
    doc = {
        "feature": "pm25_lag_1",
        "reference": "same hours of the calendar in earlier years",
        "years": fp["baseline_years"],
        "replay_start": params["replay"]["start"],
        "replay_hours": replay_hours(params["replay"]),
        "week_hours": fp["drift_window_hours"],
        "n_bins": fp["psi_bins"],
        "bin_rule": "bin index = number of edges e with e <= value",
        "week_rule": "a live window whose last hour is replay hour h "
        "(hours since replay_start) uses week h // week_hours",
        "cities": stats,
    }
    (reports / "baseline_stats.json").write_text(
        json.dumps(doc, indent=2), encoding="utf-8"
    )
    first, last = fp["threshold_blocks"]
    thr_doc = {
        "feature": "pm25_lag_1",
        "percentile": fp["threshold_percentile"],
        "years": fp["baseline_years"],
        "blocks": [first, last],
        "rule": "leave-one-year-out: each block of each reference year against "
        "the same block of the other years",
        "cities": thresholds,
    }
    (reports / "drift_thresholds.json").write_text(
        json.dumps(thr_doc, indent=2), encoding="utf-8"
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
