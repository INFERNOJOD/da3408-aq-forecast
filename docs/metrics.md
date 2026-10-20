# Measured Numbers

All numbers were measured on the project VM (4 CPU, 7.2 GB RAM, ARM64, Ubuntu).
Spark runs in local mode with driver memory 3g and 8 shuffle partitions.

## Stage 4: ingest (CSV to Parquet, Spark)

| What | Value |
|------|-------|
| Tables converted | 5 (city_day, city_hour, station_day, station_hour, stations) |
| Total rows | 3,434,754 |
| Stage time (3 runs) | 8.0 s, 8.4 s, 8.2 s |
| Throughput | about 410,000 to 430,000 rows/sec |
| Largest table | station_hour: 2,589,083 rows, about 2.5 s to convert |
| Size on disk | CSV 283 MB, Parquet 65 MB (4.4x smaller) |
| Peak Spark memory (JVM RSS) | about 1.2 GB (limit: 3 GB driver) |
| Row-count check | CSV rows equal Parquet rows for all 5 tables |

How to read this: the stage does more work than just reading.
It counts the CSV lines, parses and converts every value, writes Parquet,
reads the Parquet back and checks the row count.
A plain Python `csv` loop that only reads the files ran at about 1,000,000 rows/sec
(see `docs/data_notes.md`). The Spark number is lower because it also writes
and verifies. The gain is in later stages: Parquet is read column by column,
so feature building does not need to parse text again.

Where the numbers come from: `reports/runs.jsonl` (one line per stage run).
