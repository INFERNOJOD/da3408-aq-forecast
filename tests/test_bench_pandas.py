import pytest
from scripts import bench_pandas_ingest as bench

CSV = (
    "City,Datetime,PM2.5,PM10,NO,NO2,NOx,NH3,CO,SO2,O3,Benzene,Toluene,Xylene,AQI,"
    "AQI_Bucket\n"
    "Delhi,2020-01-01 01:00:00,50.5,,1,2,3,4,5,6,7,8,9,10,,\n"
    "Delhi,2020-01-01 02:00:00,,90,1,2,3,4,5,6,7,8,9,10,120,Moderate\n"
)


def test_pandas_ingest_counts_match(tmp_path, monkeypatch):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "city_hour.csv").write_text(CSV)
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(bench, "RAW", tmp_path / "raw")
    assert bench.ingest_table("city_hour", out) == (2, 2)
    assert (out / "city_hour.parquet").exists()


def test_pandas_ingest_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "RAW", tmp_path)
    with pytest.raises(FileNotFoundError):
        bench.ingest_table("city_hour", tmp_path)
