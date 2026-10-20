import copy
import json

import pytest
from src.common.config import load_params
from src.common.errors import DataValidationError
from src.pipeline import ingest, validate

CFG = load_params()["validate"]
REPLAY = load_params()["replay"]


def good_profile(table="city_hour"):
    columns = {
        c: {"nulls": 0, "negative": 0, "over_limit": 0, "at_limit": 0, "max": 10.0}
        for c in validate.VALUE_COLUMNS
    }
    return {
        "schema": [
            (f.name, f.dataType.simpleString()) for f in ingest.SCHEMAS[table].fields
        ],
        "rows": 100,
        "null_key": 0,
        "null_time": 0,
        "time_min": "2020-01-01 01:00:00",
        "time_max": "2020-06-01 00:00:00",
        "duplicates": 0,
        "off_hour": 0,
        "columns": columns,
        "buckets": ["Good", "Severe"],
    }


def by_name(checks):
    return {c["check"]: c for c in checks}


def test_params_have_a_ceiling_for_every_value_column():
    assert set(CFG["max_values"]) == set(validate.VALUE_COLUMNS)
    assert all(isinstance(v, (int, float)) for v in CFG["max_values"].values())


def test_good_profile_passes_every_check():
    checks = validate.check_table("city_hour", good_profile(), CFG)
    assert {c["status"] for c in checks} == {validate.PASS}


def test_schema_mismatch_fails():
    prof = good_profile()
    prof["schema"] = prof["schema"][:-1]
    assert by_name(validate.check_table("city_hour", prof, CFG))["schema"][
        "status"
    ] == (validate.FAIL)


def test_empty_nulls_and_duplicates_fail():
    prof = good_profile()
    prof.update(rows=0, null_key=2, duplicates=3)
    res = by_name(validate.check_table("city_hour", prof, CFG))
    assert res["not_empty"]["status"] == validate.FAIL
    assert res["no_null_key_or_time"]["status"] == validate.FAIL
    assert "3 duplicate" in res["no_duplicates"]["detail"]


def test_ceiling_message_names_column_limit_and_count():
    prof = good_profile()
    prof["columns"]["PM2.5"]["over_limit"] = 12
    res = by_name(validate.check_table("city_hour", prof, CFG))
    assert res["values_below_ceiling"]["status"] == validate.FAIL
    assert res["values_below_ceiling"]["detail"] == "PM2.5 > 1000 in 12 rows"


def test_negative_values_fail():
    prof = good_profile()
    prof["columns"]["CO"]["negative"] = 4
    res = by_name(validate.check_table("city_hour", prof, CFG))
    assert res["no_negative_values"]["status"] == validate.FAIL
    assert "CO < 0 in 4 rows" in res["no_negative_values"]["detail"]


@pytest.mark.parametrize(
    "tmin, tmax",
    [
        ("2014-12-31 23:00:00", "2020-01-01 00:00:00"),
        ("2020-01-01 00:00:00", "2021-03-01 00:00:00"),
    ],
)
def test_time_range_outside_fails(tmin, tmax):
    prof = good_profile()
    prof.update(time_min=tmin, time_max=tmax)
    res = by_name(validate.check_table("city_hour", prof, CFG))
    assert res["time_range"]["status"] == validate.FAIL


def test_off_hour_only_checked_for_hourly_tables():
    prof = good_profile("city_hour")
    prof["off_hour"] = 5
    assert (
        by_name(validate.check_table("city_hour", prof, CFG))["on_the_hour"]["status"]
        == validate.FAIL
    )
    daily = by_name(validate.check_table("city_day", good_profile("city_day"), CFG))
    assert "on_the_hour" not in daily


def test_unknown_bucket_and_high_missing_share_only_warn():
    prof = good_profile()
    prof["buckets"] = ["Good", "Weird"]
    prof["columns"]["PM2.5"]["nulls"] = 80
    res = by_name(validate.check_table("city_hour", prof, CFG))
    assert res["aqi_bucket_names"]["status"] == validate.WARN
    assert res["pm25_missing_share"]["status"] == validate.WARN
    report = validate.build_report(list(res.values()), {})
    assert report["status"] == "passed" and report["n_warnings"] == 2


def test_empty_table_has_zero_missing_share():
    prof = good_profile()
    prof["rows"] = 0
    assert validate._missing_share(prof, "PM2.5") == 0.0


def test_check_cities_pass_and_each_failure():
    ok = {"hours": 30000, "pm25_present": 28000, "replay_present": 2300}
    res = validate.check_cities({"Delhi": ok}, ["Delhi"], REPLAY, CFG)
    assert res[0]["status"] == validate.PASS

    few = dict(ok, hours=100)
    sparse = dict(ok, pm25_present=100)
    gap = dict(ok, replay_present=100)
    res = validate.check_cities(
        {"A": few, "B": sparse, "C": gap}, ["A", "B", "C", "Missing"], REPLAY, CFG
    )
    assert [r["status"] for r in res] == [validate.FAIL] * 4
    assert "hourly rows" in res[0]["detail"]
    assert "PM2.5 present in only" in res[1]["detail"]
    assert "replay hours" in res[2]["detail"]
    assert "no hourly data" in res[3]["detail"]


def test_check_stations():
    res = validate.check_stations(
        {"duplicate_ids": 0, "unknown_ids": {"station_day": 0, "station_hour": 3}}
    )
    assert res[0]["status"] == validate.PASS
    assert [r["status"] for r in res[1:]] == [validate.PASS, validate.WARN]
    bad = validate.check_stations({"duplicate_ids": 2, "unknown_ids": {}})
    assert bad[0]["status"] == validate.FAIL


def test_build_report_counts_failures():
    checks = [
        validate.make_check("t", "a", validate.PASS, ""),
        validate.make_check("t", "b", validate.FAIL, ""),
    ]
    rep = validate.build_report(checks, {})
    assert rep["status"] == "failed" and rep["n_failed"] == 1 and rep["n_passed"] == 1


# ---- Spark integration on tiny files ------------------------------------
HEADER = (
    "{k},{t},PM2.5,PM10,NO,NO2,NOx,NH3,CO,SO2,O3,Benzene,Toluene,Xylene,AQI,"
    "AQI_Bucket\n"
)
ROW = "{k},{t},{pm},20,1,2,3,4,5,6,7,8,9,10,100,Moderate\n"


def write_raw(raw, pm_values):
    raw.mkdir(parents=True, exist_ok=True)
    hours = [f"2020-03-25 0{i}:00:00" for i in range(len(pm_values))]
    hour_csv = HEADER.format(k="City", t="Datetime") + "".join(
        ROW.format(k="Delhi", t=h, pm=pm)
        for h, pm in zip(hours, pm_values, strict=True)
    )
    day_csv = HEADER.format(k="City", t="Date") + ROW.format(
        k="Delhi", t="2020-03-25", pm=50
    )
    st_hour = HEADER.format(k="StationId", t="Datetime") + ROW.format(
        k="S1", t=hours[0], pm=50
    )
    st_day = HEADER.format(k="StationId", t="Date") + ROW.format(
        k="S1", t="2020-03-25", pm=50
    )
    (raw / "city_hour.csv").write_text(hour_csv)
    (raw / "city_day.csv").write_text(day_csv)
    (raw / "station_hour.csv").write_text(st_hour)
    (raw / "station_day.csv").write_text(st_day)
    (raw / "stations.csv").write_text(
        "StationId,StationName,City,State,Status\nS1,One,Delhi,Delhi,Active\n"
    )


def tiny_params(tmp_path):
    params = copy.deepcopy(load_params())
    params["paths"] = {
        "raw_dir": str(tmp_path / "raw"),
        "interim_dir": str(tmp_path / "interim"),
        "reports_dir": str(tmp_path / "reports"),
    }
    params["spark"] = {"driver_memory": "512m", "shuffle_partitions": 2, "cores": 2}
    params["cities"] = ["Delhi"]
    params["replay"] = {"start": "2020-03-25 00:00:00", "end": "2020-03-25 03:00:00"}
    params["validate"].update(min_city_hours=2, min_replay_coverage=0.5)
    return params


@pytest.fixture
def tiny_stage(spark, tmp_path, monkeypatch):
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    monkeypatch.setattr(validate, "build_spark", lambda *a, **k: spark)
    monkeypatch.setattr(spark, "stop", lambda: None)

    def prepare(pm_values):
        params = tiny_params(tmp_path)
        write_raw(tmp_path / "raw", pm_values)
        for name in params["ingest"]["tables"]:
            ingest.ingest_table(spark, name, tmp_path / "raw", tmp_path / "interim")
        return params

    return prepare


def test_profile_table_counts(spark, tmp_path, tiny_stage):
    params = tiny_stage([10, 1000, 2000, 5])
    df = spark.read.parquet(str(tmp_path / "interim" / "city_hour"))
    prof = validate.profile_table(df, "city_hour", CFG["max_values"])
    assert prof["rows"] == 4 and prof["duplicates"] == 0
    assert prof["time_min"] == "2020-03-25 00:00:00"
    assert prof["columns"]["PM2.5"]["over_limit"] == 1
    assert prof["columns"]["PM2.5"]["at_limit"] == 1
    assert prof["buckets"] == ["Moderate"]
    assert params["cities"] == ["Delhi"]


def test_validate_all_passes_on_good_data(tmp_path, tiny_stage):
    params = tiny_stage([10, 20, 30, 40])
    result = validate.validate_all(params)
    assert result["rows_out"] == 4 + 1 + 1 + 1
    report = json.loads((tmp_path / "reports" / "validation.json").read_text())
    assert report["status"] == "passed" and report["n_failed"] == 0


def test_validate_all_fails_on_impossible_value(tmp_path, tiny_stage):
    params = tiny_stage([10, 2000, 30, 40])
    with pytest.raises(DataValidationError, match="PM2.5 > 1000 in 1 rows"):
        validate.validate_all(params)
    report = json.loads((tmp_path / "reports" / "validation.json").read_text())
    assert report["status"] == "failed"


def test_validate_all_reports_missing_tables(tmp_path, spark, monkeypatch):
    monkeypatch.setattr(validate, "build_spark", lambda *a, **k: spark)
    monkeypatch.setattr(spark, "stop", lambda: None)
    params = tiny_params(tmp_path)
    (tmp_path / "interim").mkdir()
    with pytest.raises(DataValidationError, match="Missing Parquet data"):
        validate.validate_all(params)
