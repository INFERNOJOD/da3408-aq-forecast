import csv

import pytest
from src.pipeline import eda, ingest

HEADER = (
    "City,Datetime,PM2.5,PM10,NO,NO2,NOx,NH3,CO,SO2,O3,Benzene,Toluene,Xylene,AQI,"
    "AQI_Bucket\n"
)
ROW = "{c},{t},{pm},,,,,,,,,,,,,\n"


@pytest.fixture
def city_hour(spark, tmp_path):
    """Tiny city_hour table: Delhi 2019 + 2020, Pune one row."""
    rows = [
        ("Delhi", "2019-04-01 00:00:00", "100"),
        ("Delhi", "2019-04-01 01:00:00", "100"),  # same as previous hour
        ("Delhi", "2019-04-01 02:00:00", ""),  # missing
        ("Delhi", "2020-04-01 00:00:00", "40"),
        ("Delhi", "2020-04-01 01:00:00", "700"),  # lands in the overflow bin
        ("Delhi", "2020-04-01 02:00:00", "0"),
        ("Pune", "2020-04-01 00:00:00", "10"),
    ]
    raw = tmp_path / "raw"
    raw.mkdir()
    text = HEADER + "".join(ROW.format(c=c, t=t, pm=pm) for c, t, pm in rows)
    (raw / "city_hour.csv").write_text(text)
    ingest.ingest_table(spark, "city_hour", raw, tmp_path / "interim")
    return spark.read.parquet(str(tmp_path / "interim" / "city_hour"))


def as_dicts(df):
    return [r.asDict() for r in df.collect()]


def test_missing_by_city_year(city_hour):
    rows = {
        (r["City"], r["year"]): r for r in as_dicts(eda.missing_by_city_year(city_hour))
    }
    assert rows[("Delhi", 2019)]["hours"] == 3
    assert rows[("Delhi", 2019)]["pm25_present"] == 2
    assert rows[("Pune", 2020)]["pm25_present"] == 1


def test_coverage_by_city(city_hour):
    rows = {r["City"]: r for r in as_dicts(eda.coverage_by_city(city_hour))}
    assert rows["Delhi"]["first_pm25"] == "2019-04-01"
    assert rows["Delhi"]["last_pm25"] == "2020-04-01"
    assert rows["Delhi"]["pm25_present"] == 5


def test_period_means_uses_only_selected_cities(city_hour):
    periods = {"a": ("2019-01-01", "2019-12-31"), "b": ("2020-01-01", "2020-12-31")}
    rows = {
        (r["period"], r["City"]): r
        for r in as_dicts(eda.period_means(city_hour, ["Delhi"], periods))
    }
    assert set(rows) == {("a", "Delhi"), ("b", "Delhi")}
    assert rows[("a", "Delhi")]["mean_pm25"] == 100
    assert rows[("b", "Delhi")]["n"] == 3


def test_histogram_bins_and_overflow(city_hour):
    periods = {"p": ("2020-01-01", "2020-12-31")}
    rows = {
        r["bin"]: r["n"] for r in as_dicts(eda.histogram(city_hour, ["Delhi"], periods))
    }
    assert rows == {0: 1, 40: 1, 500: 1}


def test_quality_flags(city_hour):
    row = as_dicts(eda.quality_flags(city_hour, ["Delhi"], 1000))[0]
    assert row["present"] == 5 and row["same_as_prev"] == 1 and row["zeros"] == 1
    assert row["at_ceiling"] == 0


def test_seasonality_stacks_hour_and_month(city_hour):
    rows = as_dicts(eda.seasonality(city_hour, ["Delhi"], "2020-01-01"))
    kinds = {r["kind"] for r in rows}
    assert kinds == {"hour", "month"}
    month = [r for r in rows if r["kind"] == "month"]
    assert month[0]["x"] == 4 and month[0]["mean_pm25"] == 100


def test_weekly_series(city_hour):
    rows = as_dicts(eda.weekly_series(city_hour, ["Delhi"], "2019-01-01", "2020-12-31"))
    assert len(rows) == 2 and rows[0]["week"] == "2019-04-01"  # a Monday


def test_stations_per_year(spark, tmp_path):
    raw, interim = tmp_path / "raw", tmp_path / "interim"
    raw.mkdir()
    header = HEADER.replace("City,", "StationId,")
    (raw / "station_hour.csv").write_text(
        header
        + ROW.format(c="S1", t="2019-01-01 01:00:00", pm=5)
        + ROW.format(c="S2", t="2019-01-01 01:00:00", pm=6)
        + ROW.format(c="S2", t="2019-01-01 02:00:00", pm=7)
        + ROW.format(c="S3", t="2019-01-01 01:00:00", pm="")
    )
    (raw / "stations.csv").write_text(
        "StationId,StationName,City,State,Status\n"
        "S1,a,Delhi,D,Active\nS2,b,Delhi,D,Active\nS3,c,Delhi,D,Active\n"
    )
    ingest.ingest_table(spark, "station_hour", raw, interim)
    ingest.ingest_table(spark, "stations", raw, interim)
    rows = as_dicts(eda.stations_per_year(spark, interim))
    assert rows == [{"City": "Delhi", "year": 2019, "stations": 2}]  # S3 has no PM2.5


def test_write_csv(tmp_path):
    path = tmp_path / "sub" / "x.csv"
    eda.write_csv([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}], path)
    with path.open() as fh:
        assert list(csv.DictReader(fh)) == [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}]
    with pytest.raises(ValueError):
        eda.write_csv([], tmp_path / "empty.csv")


def test_rows_rounds_floats(city_hour):
    rows = eda._rows(
        eda.period_means(city_hour, ["Delhi"], {"a": ("2019-01-01", "2021-01-01")})
    )
    assert rows[0]["mean_pm25"] == 188.0  # (100 + 100 + 40 + 700 + 0) / 5 = 188
