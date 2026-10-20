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

### Benchmark: Spark vs pandas on the same ingest job

Same job, same 5 files, same column types: read the CSV, write Parquet, read the
Parquet back, check that its row count equals the CSV line count.
Script: `scripts/bench_pandas_ingest.py` (pandas 3.0, pyarrow 26, one thread).
Spark: Stage 4 (`local[4]`, 3 GB driver). Both timed over the whole job, 3 runs each.

| | Spark (Stage 4) | pandas |
|---|---|---|
| Time per run | 8.0, 8.4, 8.2 s | 3.9, 3.7, 3.4 s |
| Throughput | about 420,000 rows/s | about 940,000 rows/s |
| Peak memory | about 1.2 GB (sampled JVM size) | about 1.0 GB (max RSS) |
| Parquet size | 65 MB | 64 MB |

Result: **pandas is about 2x faster on this data.** This is expected.
The raw data is only 283 MB and fits easily in memory. Spark pays fixed costs:
about 1.2 s to start the JVM (the Spark time above includes it) and extra work to
plan and schedule each of the 5 jobs. Both give the same row counts and almost the
same file size.

Why we still use Spark: it is the engine the course requires, and it does not hold
the whole table in memory, so the same code keeps working if the data grows beyond
RAM. We have not tested larger data, so that point is a design reason, not a
measured result. The two memory numbers are measured differently, so compare them
only roughly.

## Stage 5: validate (Spark)

| What | Value |
|------|-------|
| Tables checked | 4 measurement tables, plus stations and the 7 selected cities |
| Rows scanned | 3,434,524 (the 230 station rows are checked separately) |
| Checks run | 48 (48 passed, 0 warnings, 0 failed) |
| Stage time (4 runs, driver 3 GB) | 32.3 s, 32.1 s, 33.5 s, 32.3 s |
| Throughput | about 102,000 to 107,000 rows/s |
| Slowest table | station_hour (2.59 M rows), about 16 s |
| Peak Spark memory, driver 3 GB | about 3.4 GB (JVM RSS) |
| Same run, driver 1 GB | finished in 34.2 s, peak about 1.4 GB |

Why validate is slower than ingest (about 105 k rows/s against about 420 k rows/s):
it computes about 70 counters per table, and it counts distinct (id, time) pairs
to find duplicates. That distinct count needs a shuffle.

On memory: the 3.4 GB peak is the JVM filling the heap it is allowed to use. It
does not need that much. With a 1 GB driver the same run gives the same answer in
almost the same time. We keep the 3 GB limit from `CLAUDE.md` for the later,
heavier stages, and never run Spark together with the full serve stack.

Data facts found by validation (full list in `reports/validation.json`):
no duplicate rows, no negative values, no missing ids or timestamps, all
timestamps on the hour. All 7 selected cities have PM2.5 for 99.9% to 100% of the
2,352 replay hours (25 Mar to 30 Jun 2020).

## Stage 5b: EDA aggregates (Spark)

| What | Value |
|------|-------|
| Command | `python -m src.pipeline.eda` |
| Output | 8 CSV files, 1,528 data rows in total (about 70 KB) |
| Time | about 9.4 s in total (session start about 1.5 s) |
| Plots | `python scripts/plot_eda.py` makes 6 PNG files in a few seconds |
