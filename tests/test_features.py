import calendar
import json
from datetime import datetime, timedelta

import pytest
from pyspark.sql import functions as spark_fn
from src.common.errors import DataValidationError
from src.common.schema import FEATURE_COLUMNS
from src.pipeline import features, ingest

HEADER = (
    "City,Datetime,PM2.5,PM10,NO,NO2,NOx,NH3,CO,SO2,O3,Benzene,Toluene,Xylene,AQI,"
    "AQI_Bucket\n"
)
START = datetime(2020, 1, 1, 0, 0, 0)
START_EPOCH = calendar.timegm(START.timetuple())  # seconds in UTC
CITIES = ["Delhi", "Chennai"]


def hour_str(i):
    return (START + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S")


def fmt(value):
    return "" if value is None else str(value)


def write_city_hour(tmp_path, rows):
    """rows: (city, hour index, pm25, other) -> city_hour.csv; other fills PM10..O3."""
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    lines = []
    for city, i, pm, other in rows:
        o = fmt(other)
        # columns: PM2.5,PM10,NO,NO2,NOx,NH3,CO,SO2,O3,Benzene,Toluene,Xylene,AQI,Bucket
        lines.append(f"{city},{hour_str(i)},{fmt(pm)},{o},,{o},,,{o},{o},{o},,,,,\n")
    (raw / "city_hour.csv").write_text(HEADER + "".join(lines))
    ingest.ingest_table(
        pytest.importorskip("pyspark").sql.SparkSession.getActiveSession(),
        "city_hour",
        raw,
        tmp_path / "interim",
    )
    return tmp_path / "interim" / "city_hour"


def series(n=200, missing=(), pm_none=(), city="Delhi"):
    """Hours 0..n-1 with pm25 = hour index; some hours absent or null."""
    return [
        (city, i, None if i in pm_none else float(i), 1.0)
        for i in range(n)
        if i not in missing
    ]


@pytest.fixture
def build(spark, tmp_path):
    def _build(rows, cities=CITIES, max_gap=3):
        path = write_city_hour(tmp_path, rows)
        city_hour = spark.read.parquet(str(path))
        df = features.build_features(city_hour, cities, max_gap)
        # Hour index counted in Spark (UTC). Python's own timestamp() would use the
        # machine's local time zone and shift every index.
        seconds = spark_fn.col("Datetime").cast("long") - START_EPOCH
        return df.withColumn("i", (seconds / 3600).cast("int"))

    return _build


def by_hour(df, city="Delhi"):
    return {
        r["Datetime"]: r.asDict()
        for r in df.filter(spark_fn.col("City") == city).collect()
    }


def utc_hours(df, city="Delhi"):
    """Map hour index -> row, using Spark (UTC) to compute the index."""
    return {
        r["i"]: r.asDict() for r in df.filter(spark_fn.col("City") == city).collect()
    }


def test_grid_adds_missing_hours(spark, tmp_path):
    path = write_city_hour(tmp_path, series(10, missing={4, 5}))
    df = spark.read.parquet(str(path))
    grid = features.complete_hourly_grid(features.select_city_hours(df, ["Delhi"]))
    assert grid.count() == 10
    missing = grid.filter(spark_fn.col("`PM2.5`").isNull()).count()
    assert missing == 2


def test_lags_count_hours_not_rows(build):
    rows = utc_hours(build(series(200, missing={10})))
    assert len(rows) == 200  # the gap hour is back on the grid
    assert rows[100]["pm25_lag_1"] == 100.0
    assert rows[100]["pm25_lag_2"] == 99.0
    assert rows[100]["pm25_lag_24"] == 77.0  # t - 23
    assert rows[100]["pm25_lag_168"] is None  # would be hour -67
    assert rows[190]["pm25_lag_168"] == 23.0  # t - 167
    assert rows[30]["pm25_lag_24"] == 7.0  # window crosses the gap hour


def test_forward_fill_limit(build):
    # hours 50..52 missing (gap of 3) -> filled; 60..63 missing (gap of 4) -> not
    rows = utc_hours(build(series(100, pm_none={50, 51, 52, 60, 61, 62, 63})))
    assert rows[52]["pm25_lag_1"] == 49.0  # filled from hour 49
    assert rows[62]["pm25_lag_1"] == 59.0  # third missing hour still filled
    assert rows[63]["pm25_lag_1"] is None  # fourth is too far


def test_targets_use_raw_values_and_are_null_at_the_end(build):
    rows = utc_hours(build(series(100, pm_none={51})))
    assert rows[50]["y_1h"] is None  # next hour has no reading: not filled
    assert rows[40]["y_1h"] == 41.0
    assert rows[40]["y_24h"] == 64.0
    assert rows[99]["y_1h"] is None
    assert rows[80]["y_24h"] is None  # hour 104 is beyond the data


def test_rolling_windows(build):
    rows = utc_hours(build(series(100)))
    assert rows[50]["pm25_roll_mean_6"] == pytest.approx(sum(range(45, 51)) / 6)
    assert rows[50]["pm25_roll_mean_24"] == pytest.approx(sum(range(27, 51)) / 24)
    assert rows[50]["pm25_roll_std_24"] > 0
    assert rows[0]["pm25_roll_std_24"] is None  # one value: no deviation


def test_features_never_use_the_future(spark, tmp_path):
    """Changing a later reading must not change any earlier feature row."""
    base = series(120)
    changed = [(c, i, (9999.0 if i == 100 else pm), o) for c, i, pm, o in base]
    out = []
    for n, rows in enumerate([base, changed]):
        sub = tmp_path / f"v{n}"
        sub.mkdir()
        path = write_city_hour(sub, rows)
        df = features.build_features(spark.read.parquet(str(path)), ["Delhi"], 3)
        out.append(
            df.filter(spark_fn.col("Datetime") < hour_ts(spark, 100)).orderBy(
                "Datetime"
            )
        )
    a = out[0].drop("y_1h", "y_24h").collect()
    b = out[1].drop("y_1h", "y_24h").collect()
    assert a == b


def hour_ts(spark, i):
    return spark_fn.lit(hour_str(i)).cast("timestamp")


def test_calendar_features(build):
    # 2020-01-01 is a Wednesday (dow 2); hour 24*3+5 is Saturday 04 Jan 05:00
    rows = utc_hours(build(series(130) + series(130, city="Chennai")))
    assert rows[0]["dow"] == 2 and rows[0]["month"] == 1 and rows[0]["hour"] == 0
    assert rows[0]["is_weekend"] == 0
    assert rows[24 * 3 + 5]["dow"] == 5 and rows[24 * 3 + 5]["is_weekend"] == 1
    assert rows[24 * 3 + 5]["hour"] == 5
    assert rows[24 * 4]["dow"] == 6
    assert rows[24 * 5]["dow"] == 0  # Monday
    assert rows[0]["city_code"] == 0
    assert (
        utc_hours(build(series(100) + series(100, city="Chennai")), "Chennai")[0][
            "city_code"
        ]
        == 1
    )


def test_train_set_hides_targets_after_cutoff(build):
    df = build(series(100))
    train = features.make_train_set(df, hour_str(60))
    rows = utc_hours(train)
    assert max(rows) == 60
    assert rows[59]["y_1h"] == 60.0 and rows[60]["y_1h"] is None
    assert rows[30]["y_24h"] == 54.0
    assert rows[40]["y_24h"] is None  # hour 64 is after the cutoff


def test_serving_set_is_inclusive(build):
    df = build(series(100))
    rows = utc_hours(features.make_serving_set(df, hour_str(10), hour_str(20)))
    assert min(rows) == 10 and max(rows) == 20 and len(rows) == 11


REPLAY = {"start": "2020-03-25 00:00:00", "end": "2020-03-27 23:00:00"}  # 72 hours


def lag_frame(spark, rows):
    """DataFrame with City, Datetime (UTC) and pm25_lag_1 from (city, 'time', value)."""
    df = spark.createDataFrame(rows, "City string, t string, pm25_lag_1 double")
    return df.withColumn("Datetime", spark_fn.to_timestamp("t")).drop("t")


def reference_rows(city, year, per_week_values, hours_per_week=24):
    """One row per hour of the 72-hour window; every week has its own value."""
    rows = []
    start = datetime(year, 3, 25)
    for week, value in enumerate(per_week_values):
        for h in range(hours_per_week):
            t = start + timedelta(hours=week * hours_per_week + h)
            rows.append((city, t.strftime("%Y-%m-%d %H:%M:%S"), float(value + h % 5)))
    return rows


def test_replay_hours():
    assert features.replay_hours(REPLAY) == 72
    assert (
        features.replay_hours(
            {"start": "2020-03-25 00:00:00", "end": "2020-06-30 23:00:00"}
        )
        == 2352
    )


def test_baseline_uses_same_calendar_hours_of_earlier_years(spark):
    rows = (
        reference_rows("Delhi", 2018, [10, 50, 100])
        + reference_rows("Delhi", 2019, [10, 50, 100])
        + reference_rows("Delhi", 2016, [10, 50, 100])  # leap year, still aligned
    )
    out = features.baseline_stats(
        lag_frame(spark, rows), ["Delhi"], REPLAY, [2016, 2019], 4, 24, 10
    )["Delhi"]
    assert out["years"] == [2016, 2018, 2019]
    assert [w["week"] for w in out["weeks"]] == [0, 1, 2]
    for week, base in zip(out["weeks"], [10, 50, 100], strict=True):
        assert week["n"] == 3 * 24
        assert min(week["edges"]) >= base and max(week["edges"]) <= base + 4
        assert sum(week["proportions"]) == pytest.approx(1.0, abs=1e-4)
        assert len(week["proportions"]) == len(week["edges"]) + 1


def test_baseline_ignores_other_years_and_hours_outside_the_window(spark):
    rows = reference_rows("Delhi", 2019, [10, 50, 100])
    rows += [
        ("Delhi", "2017-03-25 05:00:00", 9999.0),  # year outside [2018, 2019]
        ("Delhi", "2019-03-24 23:00:00", 9999.0),  # one hour before the window
        ("Delhi", "2019-03-28 00:00:00", 9999.0),  # one hour after the window
    ]
    out = features.baseline_stats(
        lag_frame(spark, rows), ["Delhi"], REPLAY, [2018, 2019], 4, 24, 10
    )["Delhi"]
    assert all(max(w["edges"]) < 9999 for w in out["weeks"])
    assert sum(w["n"] for w in out["weeks"]) == 72


def test_baseline_constant_values_give_one_edge(spark):
    rows = reference_rows("Delhi", 2019, [5, 5, 5])
    rows = [(c, t, 5.0) for c, t, _ in rows]
    out = features.baseline_stats(
        lag_frame(spark, rows), ["Delhi"], REPLAY, [2019, 2019], 4, 24, 10
    )["Delhi"]
    assert out["weeks"][0]["edges"] == [5.0]
    assert out["weeks"][0]["proportions"] == [0.0, 1.0]


def test_baseline_needs_enough_values_in_every_week(spark):
    rows = reference_rows("Delhi", 2019, [10, 50, 100])
    df = lag_frame(spark, rows)
    with pytest.raises(DataValidationError, match="at least 1000"):
        features.baseline_stats(df, ["Delhi"], REPLAY, [2019, 2019], 4, 24, 1000)
    with pytest.raises(DataValidationError, match="Chennai week 0"):
        features.baseline_stats(df, ["Chennai"], REPLAY, [2019, 2019], 4, 24, 10)


def test_run_features_end_to_end(spark, tmp_path, monkeypatch):
    # Recent hours 0..399 plus 61 hours of 2019 that match the replay window's
    # calendar position (replay starts at hour 300 = 2020-01-13 12:00).
    old = range(-8460, -8399)
    rows = []
    for city in CITIES:
        rows += series(400, city=city)
        rows += [(city, i, float(100 + i % 7), 1.0) for i in old]
    write_city_hour(tmp_path, rows)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "validation.json").write_text('{"status": "passed"}')
    params = {
        "paths": {
            "interim_dir": str(tmp_path / "interim"),
            "features_dir": str(tmp_path / "features"),
            "reports_dir": str(tmp_path / "reports"),
        },
        "spark": {"driver_memory": "512m", "shuffle_partitions": 2, "cores": 2},
        "cities": CITIES,
        "cutoff": hour_str(299),
        "replay": {"start": hour_str(300), "end": hour_str(349)},
        "features": {
            "max_ffill_hours": 3,
            "serving_start": hour_str(200),
            "psi_bins": 4,
            "baseline_years": [2019, 2019],
            "drift_window_hours": 24,
            "baseline_min_n": 2,
        },
    }
    monkeypatch.setattr(features, "build_spark", lambda *a, **k: spark)
    monkeypatch.setattr(spark, "stop", lambda: None)
    result = features.run_features(params)
    assert result["rows_in"] == 2 * (400 + 61)
    train = spark.read.parquet(str(tmp_path / "features" / "train.parquet"))
    serving = spark.read.parquet(str(tmp_path / "features" / "serving.parquet"))
    assert train.count() == 2 * (8460 + 300)  # hourly grid from 2019 to hour 299
    assert serving.count() == 2 * 150  # hours 200..349 per city
    assert result["rows_out"] == train.count() + serving.count()
    assert set(FEATURE_COLUMNS) <= set(train.columns)
    doc = json.loads((tmp_path / "reports" / "baseline_stats.json").read_text())
    assert doc["feature"] == "pm25_lag_1" and set(doc["cities"]) == set(CITIES)
    assert doc["years"] == [2019, 2019] and doc["week_hours"] == 24
    assert [w["week"] for w in doc["cities"]["Delhi"]["weeks"]] == [0, 1, 2]


def test_baseline_years_must_end_before_the_replay_year(spark, tmp_path):
    params = {
        "paths": {"reports_dir": str(tmp_path)},
        "replay": {"start": "2020-03-25 00:00:00", "end": "2020-06-30 23:00:00"},
        "features": {"baseline_years": [2016, 2020]},
    }
    (tmp_path / "validation.json").write_text('{"status": "passed"}')
    with pytest.raises(DataValidationError, match="must end before the replay"):
        features.run_features(
            {
                **params,
                "paths": {
                    "reports_dir": str(tmp_path),
                    "interim_dir": "x",
                    "features_dir": "y",
                },
                "cities": [],
                "cutoff": "c",
            }
        )


def test_features_refuse_to_run_without_a_passed_validation(tmp_path):
    with pytest.raises(DataValidationError, match="validate stage first"):
        features.require_validation_passed(tmp_path)
    (tmp_path / "validation.json").write_text('{"status": "failed"}')
    with pytest.raises(DataValidationError, match="'failed'"):
        features.require_validation_passed(tmp_path)
    (tmp_path / "validation.json").write_text("not json")
    with pytest.raises(DataValidationError, match="not valid JSON"):
        features.require_validation_passed(tmp_path)
    (tmp_path / "validation.json").write_text('{"status": "passed"}')
    features.require_validation_passed(tmp_path)  # no error
