"""Benchmark: the same ingest job as Stage 4, done with pandas.

Job: read each raw CSV, write Parquet, read the Parquet back and check that
its row count equals the CSV line count. Same tables, same column types as
src/pipeline/ingest.py. Used only to compare speed with Spark.

Run: ``python scripts/bench_pandas_ingest.py [runs]``
"""

import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

RAW = Path("data/raw")
POLLUTANTS = ["PM2.5", "PM10", "NO", "NO2", "NOx", "NH3", "CO", "SO2", "O3"]
POLLUTANTS += ["Benzene", "Toluene", "Xylene", "AQI"]
TABLES = {  # table -> (time column or None, string columns)
    "city_day": ("Date", ["City", "AQI_Bucket"]),
    "city_hour": ("Datetime", ["City", "AQI_Bucket"]),
    "station_day": ("Date", ["StationId", "AQI_Bucket"]),
    "station_hour": ("Datetime", ["StationId", "AQI_Bucket"]),
    "stations": (None, ["StationId", "StationName", "City", "State", "Status"]),
}


def count_csv_rows(path: Path) -> int:
    """Count data rows (lines minus header), same check as the Spark stage."""
    with path.open("rb") as fh:
        return max(sum(1 for _ in fh) - 1, 0)


def ingest_table(name: str, out_dir: Path) -> tuple[int, int]:
    """Convert one table; return (rows_in, rows_out)."""
    time_col, str_cols = TABLES[name]
    dtypes = {c: "string" for c in str_cols}
    if time_col:
        dtypes[time_col] = "string"
        dtypes.update({c: "float64" for c in POLLUTANTS})
    path = RAW / f"{name}.csv"
    rows_in = count_csv_rows(path)
    df = pd.read_csv(path, dtype=dtypes, encoding="utf-8-sig")
    if time_col:
        df[time_col] = pd.to_datetime(df[time_col])
    df.to_parquet(out_dir / f"{name}.parquet", index=False)
    rows_out = pq.ParquetFile(out_dir / f"{name}.parquet").metadata.num_rows
    if rows_in != rows_out:
        raise RuntimeError(f"{name}: {rows_in} CSV rows vs {rows_out} Parquet rows")
    return rows_in, rows_out


def main(runs: int) -> None:
    """Time the whole job ``runs`` times and print a summary."""
    for i in range(runs):
        out_dir = Path(tempfile.mkdtemp(prefix="bench_pandas_"))
        start = time.perf_counter()
        total = sum(ingest_table(n, out_dir)[1] for n in TABLES)
        secs = time.perf_counter() - start
        size_mb = sum(f.stat().st_size for f in out_dir.iterdir()) / 1e6
        shutil.rmtree(out_dir)
        print(
            f"run {i + 1}: {secs:.1f} s, {total} rows, {total / secs:.0f} rows/s, "
            f"parquet {size_mb:.0f} MB"
        )
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"peak memory (max RSS): {peak_mb:.0f} MB")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
