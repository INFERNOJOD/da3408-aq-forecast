import json

import pytest
from pyspark.sql import functions as spark_fn
from src.common.errors import DataValidationError
from src.pipeline import ingest

HOUR_CSV = (
    "City,Datetime,PM2.5,PM10,NO,NO2,NOx,NH3,CO,SO2,O3,Benzene,Toluene,Xylene,AQI,"
    "AQI_Bucket\n"
    "Delhi,2020-01-01 01:00:00,50.5,,1,2,3,4,5,6,7,8,9,10,,\n"
    "Delhi,2020-01-01 02:00:00,,90,1,2,3,4,5,6,7,8,9,10,120,Moderate\n"
)


def make_params(tmp_path, tables):
    return {
        "paths": {
            "raw_dir": str(tmp_path / "raw"),
            "interim_dir": str(tmp_path / "interim"),
            "reports_dir": str(tmp_path / "reports"),
        },
        "spark": {"driver_memory": "512m", "shuffle_partitions": 2, "cores": 2},
        "ingest": {"tables": tables},
        "cutoff": "2020-03-24 23:00:00",
    }


def test_schemas_cover_all_tables_with_16_measurement_columns():
    for name in ["city_day", "city_hour", "station_day", "station_hour"]:
        assert len(ingest.SCHEMAS[name].fields) == 16
    assert len(ingest.SCHEMAS["stations"].fields) == 5


def test_count_csv_rows(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("h\n1\n2\n3\n")
    assert ingest.count_csv_rows(f) == 3
    empty = tmp_path / "e.csv"
    empty.write_text("")
    assert ingest.count_csv_rows(empty) == 0


def test_ingest_table_roundtrip(spark, tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "interim"
    raw.mkdir()
    (raw / "city_hour.csv").write_text(HOUR_CSV)
    res = ingest.ingest_table(spark, "city_hour", raw, out)
    assert res == {"rows_in": 2, "rows_out": 2}
    df = spark.read.parquet(str(out / "city_hour"))
    # hour() runs inside Spark (UTC session), unlike collect() which converts
    # timestamps to the Python process's local time zone.
    df = df.withColumn("h", spark_fn.hour("Datetime"))
    rows = {r["h"]: r for r in df.collect()}
    assert rows[1]["PM2.5"] == 50.5 and rows[1]["PM10"] is None
    assert rows[2]["PM2.5"] is None and rows[2]["AQI_Bucket"] == "Moderate"


def test_ingest_table_stations_with_bom(spark, tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "interim"
    raw.mkdir()
    (raw / "stations.csv").write_text(
        "﻿StationId,StationName,City,State,Status\n"
        'AP001,"Secretariat, Amaravati",Amaravati,Andhra Pradesh,Active\n',
        encoding="utf-8",
    )
    ingest.ingest_table(spark, "stations", raw, out)
    row = spark.read.parquet(str(out / "stations")).collect()[0]
    assert row["StationId"] == "AP001"
    assert row["StationName"] == "Secretariat, Amaravati"


def test_missing_file_raises(spark, tmp_path):
    (tmp_path / "raw").mkdir()
    with pytest.raises(DataValidationError, match="not found"):
        ingest.ingest_table(spark, "city_hour", tmp_path / "raw", tmp_path / "o")


def test_unknown_table_raises(spark, tmp_path):
    with pytest.raises(DataValidationError, match="No schema"):
        ingest.ingest_table(spark, "bogus", tmp_path, tmp_path)


def test_malformed_row_fails_fast(spark, tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "interim"
    raw.mkdir()
    bad = HOUR_CSV + "Delhi,2020-01-01 03:00:00,not-a-number,,,,,,,,,,,,,\n"
    (raw / "city_hour.csv").write_text(bad)
    with pytest.raises(DataValidationError):
        ingest.ingest_table(spark, "city_hour", raw, out)


def test_run_stage_records_success_and_failure(spark, tmp_path, monkeypatch):
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    params = make_params(tmp_path, ["city_hour"])
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "city_hour.csv").write_text(HOUR_CSV)
    monkeypatch.setattr(ingest, "build_spark", lambda *a, **k: spark)
    monkeypatch.setattr(spark, "stop", lambda: None)  # keep shared session alive
    rec = ingest.run_stage("ingest", lambda: ingest.ingest_all(params), params)
    assert rec["status"] == "success" and rec["rows_out"] == 2
    assert rec["rows_per_sec"] > 0

    params["ingest"]["tables"] = ["stations"]  # file missing -> failure
    with pytest.raises(Exception, match="not found"):
        ingest.run_stage("ingest", lambda: ingest.ingest_all(params), params)

    lines = (tmp_path / "reports" / "runs.jsonl").read_text().splitlines()
    statuses = [json.loads(line)["status"] for line in lines]
    assert statuses == ["success", "failed"]
    last = json.loads(lines[-1])
    assert "not found" in last["error"]
