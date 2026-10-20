"""Stage 2 of the DVC pipeline: check the Parquet tables before using them.

Two parts, kept apart on purpose:
  1. ``profile_*`` functions use Spark to collect plain numbers (counts, mins,
     maxes) in one pass per table.
  2. ``check_*`` functions are pure Python: they turn those numbers into
     pass / warn / fail results. They need no Spark, so they are easy to test.

A "fail" is a hard error and stops the pipeline. A "warn" is only reported.
The full result is saved to reports/validation.json.

Run: ``python -m src.pipeline.validate``
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as spark_fn

from src.common.config import load_env, load_params
from src.common.errors import DataValidationError
from src.common.logging_setup import configure_logging, get_logger
from src.common.spark import build_spark
from src.common.stage_runner import run_stage
from src.pipeline.ingest import POLLUTANTS, SCHEMAS

log = get_logger(__name__)

# table -> (key column, time column, is hourly)
MEASUREMENT_TABLES = {
    "city_day": ("City", "Date", False),
    "city_hour": ("City", "Datetime", True),
    "station_day": ("StationId", "Date", False),
    "station_hour": ("StationId", "Datetime", True),
}
VALUE_COLUMNS = [*POLLUTANTS, "AQI"]
AQI_BUCKETS = {"Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"}
TIME_FORMAT = "yyyy-MM-dd HH:mm:ss"

PASS, WARN, FAIL = "pass", "warn", "fail"


def _col(name: str):
    """Column reference that is safe for names with dots, like PM2.5."""
    return spark_fn.col(f"`{name}`")


def make_check(
    table: str, name: str, status: str, detail: str, value: Any = None
) -> dict[str, Any]:
    """Build one check result in the format stored in validation.json."""
    return {
        "table": table,
        "check": name,
        "status": status,
        "detail": detail,
        "value": value,
    }


# --------------------------------------------------------------------------
# Part 1: Spark profiling (collects numbers only)
# --------------------------------------------------------------------------
def profile_table(
    df: DataFrame, table: str, max_values: dict[str, float]
) -> dict[str, Any]:
    """Collect all numbers needed to check one measurement table.

    Everything comes from one Spark aggregation, so the data is scanned once.
    """
    key, time_col, hourly = MEASUREMENT_TABLES[table]
    exprs = [
        spark_fn.count(spark_fn.lit(1)).alias("rows"),
        spark_fn.sum(_col(key).isNull().cast("int")).alias("null_key"),
        spark_fn.sum(_col(time_col).isNull().cast("int")).alias("null_time"),
        spark_fn.date_format(spark_fn.min(_col(time_col)), TIME_FORMAT).alias("tmin"),
        spark_fn.date_format(spark_fn.max(_col(time_col)), TIME_FORMAT).alias("tmax"),
        spark_fn.countDistinct(_col(key), _col(time_col)).alias("distinct_pairs"),
    ]
    if hourly:
        exprs.append(
            spark_fn.sum(
                (
                    spark_fn.minute(_col(time_col)) + spark_fn.second(_col(time_col))
                    > 0
                ).cast("int")
            ).alias("off_hour")
        )
    for i, name in enumerate(VALUE_COLUMNS):
        c = _col(name)
        limit = max_values[name]
        exprs += [
            spark_fn.sum(c.isNull().cast("int")).alias(f"v{i}_nulls"),
            spark_fn.sum((c < 0).cast("int")).alias(f"v{i}_neg"),
            spark_fn.sum((c > limit).cast("int")).alias(f"v{i}_over"),
            spark_fn.sum((c == limit).cast("int")).alias(f"v{i}_at_limit"),
            spark_fn.max(c).alias(f"v{i}_max"),
        ]
    exprs.append(spark_fn.collect_set("AQI_Bucket").alias("buckets"))
    row = df.agg(*exprs).collect()[0].asDict()

    columns = {}
    for i, name in enumerate(VALUE_COLUMNS):
        columns[name] = {
            "nulls": row[f"v{i}_nulls"] or 0,
            "negative": row[f"v{i}_neg"] or 0,
            "over_limit": row[f"v{i}_over"] or 0,
            "at_limit": row[f"v{i}_at_limit"] or 0,
            "max": row[f"v{i}_max"],
        }
    return {
        "schema": [(f.name, f.dataType.simpleString()) for f in df.schema.fields],
        "rows": row["rows"],
        "null_key": row["null_key"] or 0,
        "null_time": row["null_time"] or 0,
        "time_min": row["tmin"],
        "time_max": row["tmax"],
        "duplicates": row["rows"] - row["distinct_pairs"],
        "off_hour": (row.get("off_hour") or 0) if hourly else 0,
        "columns": columns,
        "buckets": sorted(b for b in (row["buckets"] or []) if b is not None),
    }


def profile_cities(
    df: DataFrame, cities: list[str], replay: dict[str, str]
) -> dict[str, dict[str, int]]:
    """Per selected city: hourly rows, non-missing PM2.5, and PM2.5 in replay window."""
    in_window = (_col("Datetime") >= spark_fn.lit(replay["start"])) & (
        _col("Datetime") <= spark_fn.lit(replay["end"])
    )
    has_pm = _col("PM2.5").isNotNull()
    rows = (
        df.filter(_col("City").isin(cities))
        .groupBy("City")
        .agg(
            spark_fn.count(spark_fn.lit(1)).alias("hours"),
            spark_fn.sum(has_pm.cast("int")).alias("pm25_present"),
            spark_fn.sum((has_pm & in_window).cast("int")).alias("replay_present"),
        )
        .collect()
    )
    return {
        r["City"]: {
            "hours": r["hours"],
            "pm25_present": r["pm25_present"] or 0,
            "replay_present": r["replay_present"] or 0,
        }
        for r in rows
    }


def profile_stations(
    spark: SparkSession, interim: Path, tables: list[str]
) -> dict[str, Any]:
    """Station id checks: duplicate ids, and ids used in data but not listed."""
    stations = spark.read.parquet(str(interim / "stations"))
    total = stations.count()
    result: dict[str, Any] = {
        "rows": total,
        "duplicate_ids": total - stations.select("StationId").distinct().count(),
        "unknown_ids": {},
    }
    for table in tables:
        used = spark.read.parquet(str(interim / table)).select("StationId").distinct()
        result["unknown_ids"][table] = used.join(
            stations.select("StationId"), "StationId", "left_anti"
        ).count()
    return result


# --------------------------------------------------------------------------
# Part 2: pure checks (numbers in, results out)
# --------------------------------------------------------------------------
def _parse_time(text: str) -> datetime:
    """Parse 'YYYY-MM-DD HH:MM:SS' (Spark output) into a datetime."""
    return datetime.fromisoformat(text)


def check_table(
    table: str, prof: dict[str, Any], cfg: dict[str, Any]
) -> list[dict[str, Any]]:
    """Turn one table's profile into check results."""
    out: list[dict[str, Any]] = []
    expected = [(f.name, f.dataType.simpleString()) for f in SCHEMAS[table].fields]
    actual = [tuple(x) for x in prof["schema"]]
    ok = actual == expected
    out.append(
        make_check(
            table,
            "schema",
            PASS if ok else FAIL,
            "Columns and types match the expected schema"
            if ok
            else f"Schema differs: expected {expected}, got {actual}",
        )
    )
    n = prof["rows"]
    out.append(
        make_check(
            table,
            "not_empty",
            PASS if n > 0 else FAIL,
            f"{n} rows" if n else "Table has no rows",
            n,
        )
    )
    nulls = prof["null_key"] + prof["null_time"]
    out.append(
        make_check(
            table,
            "no_null_key_or_time",
            PASS if nulls == 0 else FAIL,
            "No missing ids or timestamps"
            if nulls == 0
            else f"{nulls} rows have a missing id or timestamp",
            nulls,
        )
    )
    dup = prof["duplicates"]
    out.append(
        make_check(
            table,
            "no_duplicates",
            PASS if dup == 0 else FAIL,
            "Every (id, time) pair is unique"
            if dup == 0
            else f"{dup} duplicate (id, time) rows",
            dup,
        )
    )
    out.append(_check_time_range(table, prof, cfg["time_range"]))
    if MEASUREMENT_TABLES[table][2]:
        off = prof["off_hour"]
        out.append(
            make_check(
                table,
                "on_the_hour",
                PASS if off == 0 else FAIL,
                "All timestamps are on the hour"
                if off == 0
                else f"{off} timestamps are not on the hour",
                off,
            )
        )
    out += _check_values(table, prof, cfg)
    unknown = set(prof["buckets"]) - AQI_BUCKETS
    out.append(
        make_check(
            table,
            "aqi_bucket_names",
            PASS if not unknown else WARN,
            "AQI_Bucket values are all known"
            if not unknown
            else f"Unknown AQI_Bucket values: {sorted(unknown)}",
        )
    )
    share = _missing_share(prof, "PM2.5")
    limit = cfg["warn_missing_share"]
    out.append(
        make_check(
            table,
            "pm25_missing_share",
            PASS if share <= limit else WARN,
            f"PM2.5 missing in {share:.1%} of rows (warn above {limit:.0%})",
            round(share, 4),
        )
    )
    return out


def _missing_share(prof: dict[str, Any], column: str) -> float:
    """Share of rows where ``column`` is null (0 for an empty table)."""
    rows = prof["rows"]
    return prof["columns"][column]["nulls"] / rows if rows else 0.0


def _check_time_range(
    table: str, prof: dict[str, Any], limits: dict[str, str]
) -> dict[str, Any]:
    """All timestamps must lie inside the allowed range."""
    if not prof["time_min"]:
        return make_check(table, "time_range", FAIL, "No timestamps found")
    low, high = _parse_time(limits["min"]), _parse_time(limits["max"])
    first, last = _parse_time(prof["time_min"]), _parse_time(prof["time_max"])
    ok = low <= first and last <= high
    detail = f"Times run from {first} to {last}"
    if not ok:
        detail += f", outside the allowed range {low} to {high}"
    return make_check(
        table,
        "time_range",
        PASS if ok else FAIL,
        detail,
        [prof["time_min"], prof["time_max"]],
    )


def _check_values(
    table: str, prof: dict[str, Any], cfg: dict[str, Any]
) -> list[dict[str, Any]]:
    """Pollutant values must be non-negative and not above the sensor ceiling."""
    bad_neg = {c: v["negative"] for c, v in prof["columns"].items() if v["negative"]}
    bad_over = {
        c: v["over_limit"] for c, v in prof["columns"].items() if v["over_limit"]
    }
    results = []
    if bad_neg:
        msg = "; ".join(f"{c} < 0 in {n} rows" for c, n in bad_neg.items())
        results.append(make_check(table, "no_negative_values", FAIL, msg, bad_neg))
    else:
        results.append(
            make_check(table, "no_negative_values", PASS, "No negative values", 0)
        )
    if bad_over:
        msg = "; ".join(
            f"{c} > {cfg['max_values'][c]} in {n} rows" for c, n in bad_over.items()
        )
        results.append(make_check(table, "values_below_ceiling", FAIL, msg, bad_over))
    else:
        results.append(
            make_check(
                table,
                "values_below_ceiling",
                PASS,
                "All values are at or below the sensor ceilings",
                0,
            )
        )
    return results


def check_cities(
    prof: dict[str, dict[str, int]],
    cities: list[str],
    replay: dict[str, str],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check that selected cities have enough history and replay-window data."""
    hours = (
        _parse_time(replay["end"]) - _parse_time(replay["start"])
    ).total_seconds() / 3600 + 1
    out = []
    for city in cities:
        p = prof.get(city)
        if p is None:
            out.append(
                make_check(
                    "city_hour", f"city_{city}", FAIL, f"{city} has no hourly data"
                )
            )
            continue
        share = p["pm25_present"] / p["hours"] if p["hours"] else 0.0
        cover = p["replay_present"] / hours
        problems = []
        if p["hours"] < cfg["min_city_hours"]:
            problems.append(
                f"only {p['hours']} hourly rows (need {cfg['min_city_hours']})"
            )
        if share < cfg["min_city_pm25_share"]:
            problems.append(f"PM2.5 present in only {share:.0%} of rows")
        if cover < cfg["min_replay_coverage"]:
            problems.append(f"only {cover:.0%} of replay hours have PM2.5")
        out.append(
            make_check(
                "city_hour",
                f"city_{city}",
                FAIL if problems else PASS,
                "; ".join(problems)
                or (
                    f"{p['hours']} rows, PM2.5 present {share:.0%}, "
                    f"replay coverage {cover:.0%}"
                ),
                {
                    "hours": p["hours"],
                    "pm25_share": round(share, 4),
                    "replay_coverage": round(cover, 4),
                },
            )
        )
    return out


def check_stations(prof: dict[str, Any]) -> list[dict[str, Any]]:
    """Station ids must be unique; unknown ids in the data are only a warning."""
    dup = prof["duplicate_ids"]
    out = [
        make_check(
            "stations",
            "unique_ids",
            PASS if dup == 0 else FAIL,
            "StationId is unique" if dup == 0 else f"{dup} duplicate StationId rows",
            dup,
        )
    ]
    for table, n in prof["unknown_ids"].items():
        out.append(
            make_check(
                table,
                "stations_known",
                PASS if n == 0 else WARN,
                "All StationIds are listed in stations.csv"
                if n == 0
                else f"{n} StationIds are not listed in stations.csv",
                n,
            )
        )
    return out


def build_report(checks: list[dict[str, Any]], stats: dict[str, Any]) -> dict[str, Any]:
    """Summarise all checks into the document written to validation.json."""
    failed = [c for c in checks if c["status"] == FAIL]
    return {
        "status": "failed" if failed else "passed",
        "n_checks": len(checks),
        "n_passed": sum(c["status"] == PASS for c in checks),
        "n_warnings": sum(c["status"] == WARN for c in checks),
        "n_failed": len(failed),
        "checks": checks,
        "stats": stats,
    }


# --------------------------------------------------------------------------
# Stage entry points
# --------------------------------------------------------------------------
def validate_all(params: dict[str, Any]) -> dict[str, int]:
    """Profile and check every table, write the report, fail on hard errors.

    Returns rows_in / rows_out (total rows checked) for the throughput record.
    """
    interim = Path(params["paths"]["interim_dir"])
    reports = Path(params["paths"]["reports_dir"])
    cfg = params["validate"]
    spark = build_spark("aq-validate", params["spark"])
    checks: list[dict[str, Any]] = []
    stats: dict[str, Any] = {}
    total = 0
    try:
        for table in MEASUREMENT_TABLES:
            path = interim / table
            if not path.is_dir():
                checks.append(
                    make_check(table, "exists", FAIL, f"Missing Parquet data: {path}")
                )
                continue
            df = spark.read.parquet(str(path))
            prof = profile_table(df, table, cfg["max_values"])
            total += prof["rows"]
            checks += check_table(table, prof, cfg)
            stats[table] = {
                "rows": prof["rows"],
                "time_min": prof["time_min"],
                "time_max": prof["time_max"],
                "missing_share": {
                    c: round(_missing_share(prof, c), 4) for c in VALUE_COLUMNS
                },
                "values_at_sensor_ceiling": {
                    c: v["at_limit"]
                    for c, v in prof["columns"].items()
                    if v["at_limit"]
                },
            }
            log.info("Validated %s: %d rows", table, prof["rows"])
        if (interim / "city_hour").is_dir():
            cities = profile_cities(
                spark.read.parquet(str(interim / "city_hour")),
                params["cities"],
                params["replay"],
            )
            checks += check_cities(cities, params["cities"], params["replay"], cfg)
            stats["selected_cities"] = cities
        if (interim / "stations").is_dir():
            station_prof = profile_stations(
                spark, interim, ["station_day", "station_hour"]
            )
            checks += check_stations(station_prof)
            stats["stations"] = station_prof
        else:
            checks.append(make_check("stations", "exists", FAIL, "Missing stations"))
    finally:
        spark.stop()

    report = build_report(checks, stats)
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "validation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    failed = [c for c in checks if c["status"] == FAIL]
    for c in checks:
        if c["status"] != PASS:
            log.warning(
                "%s %s/%s: %s", c["status"].upper(), c["table"], c["check"], c["detail"]
            )
    if failed:
        reasons = "; ".join(f"{c['table']}/{c['check']}: {c['detail']}" for c in failed)
        raise DataValidationError(f"{len(failed)} hard check(s) failed: {reasons}")
    log.info(
        "Validation passed: %d checks, %d warnings",
        report["n_checks"],
        report["n_warnings"],
    )
    return {"rows_in": total, "rows_out": total}


def main() -> None:
    """Command-line entry point used by dvc.yaml."""
    configure_logging()
    load_env()
    params = load_params()
    run_stage("validate", lambda: validate_all(params), params)


if __name__ == "__main__":
    main()
