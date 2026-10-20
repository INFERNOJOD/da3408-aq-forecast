# Measured Numbers

All numbers were measured on the project VM (4 CPU, 7.2 GB RAM, ARM64, Ubuntu).
Spark runs in local mode with 8 shuffle partitions. The driver memory was 3g for the first measurements and was lowered to 2g afterwards (see "Driver memory 2g" at the end of this file). Each table says which one it used.

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
almost the same time. I first kept the 3 GB limit from `CLAUDE.md` for the later,
heavier stages. I lowered it to 2 GB afterwards (see the last section). Spark never runs together with the full serve stack.

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

## Driver memory 2g

The VM has about 3.9 GB free, and the 1 GB test above showed that validate does not need 3 GB.
I set the Spark driver to 2g in `CLAUDE.md` and `params.yaml`, then ran the whole pipeline again.

| What | Driver 3g | Driver 2g |
|------|-----------|-----------|
| ingest time | 8.0 to 8.4 s | 8.9 s |
| validate time | 32.1 to 33.5 s | 33.3 s |
| Peak Spark memory while both ran (JVM RSS) | 3.4 GB (validate alone) | about 2.4 GB (ingest and validate) |

Both stages give the same results with 2g. The times are within the run-to-run spread I saw before.
Ingest at 2g is a single run, so I do not read anything into the 0.5 s difference.

## Stage 6: features (Spark, driver 2g)

| What | Value |
|------|-------|
| Input | 287,083 `city_hour` rows of the 7 selected cities (`rows_in`). The hourly grid adds no rows on this data: none of the 7 cities has an absent hour, and gaps are null values |
| Training rows (`train.parquet`, hours up to 2020-03-24 23:00) | 270,612 |
| Serving rows (`serving.parquet`, 2020-01-01 to 2020-06-30) | 30,576 (4,368 per city) |
| Stage time (5 runs) | 12.4 s, 13.0 s, 11.8 s, 12.3 s, 13.0 s |
| Output | 301,188 rows written (`rows_out`: train 270,612 + serving 30,576) |
| Throughput | about 23,000 to 25,500 rows/s (rows written per second) |
| Disk size | train 15 MB, serving 1.8 MB |
| Peak Spark memory (JVM RSS) | about 2.5 GB over a full `dvc repro` of ingest, validate and features |

Features process fewer rows per second than ingest and validate. I did not profile where the
time goes. The likely cause is that every city needs several window operations (lags, rolling
mean and standard deviation, forward fill), each ordered by time, and the data is small enough
that fixed job costs matter, including the Spark start of about 1.5 s. The rows/s figure also
counts rows that appear in both files (the replay hours up to the cutoff), so it should not be
compared directly with the other stages.

Full pipeline, driver 2g, one `dvc repro` from a clean state: ingest 8.8 s, validate 32.9 s,
features 13.0 s, about 55 s in total.

Correctness check (not a speed number): I recomputed every feature column in pandas for
Hyderabad (has gaps) and Kolkata (starts late), 4,368 serving rows each, 21 columns. There were
0 mismatches. In the training file, no row has a target from after the cutoff.

## Stage 7: train (Ridge, LightGBM and two baselines, no Spark)

Training does not use Spark. It reads `train.parquet` with pandas. Settings: cutoff
2020-03-24 23:00, evaluation window 3 days, recency half-life 30 days, LightGBM with L1 loss
and 400 trees, fixed seed, deterministic.

| What | 1 h ahead | 24 h ahead |
|------|----------:|-----------:|
| Training rows | 252,949 | 252,903 |
| Effective training rows (weights, see below) | 14,542 | 14,542 |
| Evaluation rows (7 cities) | 497 | 336 |
| Evaluation rows per city | 71 | 48 |

Mean absolute error on the evaluation window, in µg/m³. All four models are scored on the same rows.

| Model | 1 h | 24 h | Mean of both |
|-------|----:|-----:|-------------:|
| Persistence | 5.13 | 14.70 | 9.92 |
| Seasonal naive | 15.49 | 14.70 | 15.10 |
| Ridge | 5.31 | 13.83 | 9.57 |
| LightGBM | 4.76 | 14.13 | 9.45 |
| LightGBM / best baseline | 0.927 | 1.022 | |

Seasonal naive equals persistence at 24 h by construction: the value one day before the target
hour is the current hour. The promotion rule in `docs/HLD.md` needs a ratio of at most 1.02, so
at 24 h this model misses it by 0.002 on 336 rows.

Per city (LightGBM against the best baseline, same rows): at 1 h it is better in 5 of 7 cities
and worse in Kolkata and Lucknow. At 24 h it is better in 4 (Delhi 16.95 against 22.67,
Hyderabad 7.00 against 8.67) and worse in Chennai, Kolkata and Lucknow. With 48 to 71 rows per
city these are weak comparisons. The full table is `per_city_mae.csv` in the MLflow run.

Error on high hours (actual PM2.5 at or above 121): 17.6 on 13 hours at 1 h and 60.7 on 10
hours at 24 h. The sample is too small to conclude anything. It does show that peaks are the weak
spot, as `docs/eda.md` predicted.

Cost and size:

| What | Value |
|------|-------|
| Whole stage (4 runs, L1 loss) | 23.6 s, 25.1 s, 26.4 s, 26.7 s |
| Same stage with the default squared loss | 10.3 s |
| LightGBM fit, per horizon | about 11 s |
| Ridge fit, per horizon | about 0.5 s |
| Saved model folder | 3.0 MB |
| Metrics in one MLflow run | 88 |

Why only 14.5k effective rows: the 30-day half-life gives a row from 30 days before the cutoff
half the weight of a recent one. The effective sample size, (sum of weights)² divided by the sum
of squared weights, is 14,542 out of 252,949 rows. The model is in practice trained on the last
few months.

### Experiment: recency half-life and loss function

I ran this once, outside the pipeline (script not kept), with the same code as the stage. LightGBM
only, mean absolute error in µg/m³. The 28-day window has 4,697 rows at 1 h and 4,536 at 24 h.
Persistence on that window: 5.92 at 1 h and 16.26 at 24 h.

| Half-life | 1 h, squared loss | 1 h, L1 | 24 h, squared loss | 24 h, L1 |
|-----------|------------------:|--------:|-------------------:|---------:|
| 30 days | 4.89 | 4.88 | 15.70 | 14.97 |
| 90 days | 4.85 | 4.78 | 15.00 | 14.31 |
| 365 days | 4.98 | 4.70 | 14.96 | 14.23 |
| no weighting | 5.27 | 4.74 | 15.29 | 14.28 |

L1 is better or equal in all 8 cells. A half-life of 30 days is the weakest choice at 24 h: it is
about 0.7 µg/m³ worse than 90 or 365 days. On the 3-day window the same comparison is mixed,
which is what a 336-row window should look like. This experiment ran before I made training
deterministic, so differences below about 0.1 are noise. I kept the 30-day half-life from the
design and did not change it.

### Check: is training repeatable?

| Setting | Three runs identical? | Largest difference between runs |
|---------|-----------------------|---------------------------------|
| LightGBM defaults | no | 4.99 µg/m³ on a single prediction |
| `deterministic` and `force_row_wise` | yes | 0 |

I use the second setting. Two forced reruns of the stage gave the same MAE (14.13 at 24 h).
`mlflow run . -e main --env-manager local` also gave 14.13. I have not run it with the
virtualenv environment manager, which would build a fresh environment.

### Check: the same-season drift reference (from Stage 6)

PSI of `pm25_lag_1` over 168 hours with 10 bins, against the reference in
`reports/baseline_stats.json`. "Normal weeks" are the weeks 1 to 13 of the replay calendar in
2016-2019, each compared with the other years (a reference needs at least 3 years). "Lockdown
weeks" are the same 13 weeks in 2020 against the saved reference. The common alarm level is 0.2.

| City | Normal weeks: n | median | 90th percentile | max | Lockdown weeks: median | min | max |
|------|----:|----:|----:|----:|----:|----:|----:|
| Delhi | 52 | 0.66 | 1.83 | 3.24 | 1.94 | 0.50 | 5.44 |
| Chennai | 50 | 0.67 | 4.07 | 6.12 | 3.98 | 1.77 | 8.29 |
| Lucknow | 48 | 0.64 | 2.21 | 5.03 | 2.58 | 0.99 | 5.75 |
| Hyderabad | 52 | 1.08 | 3.42 | 4.27 | 1.26 | 0.10 | 2.96 |
| Bengaluru | 46 | 0.64 | 1.87 | 2.50 | 1.67 | 0.54 | 4.38 |
| Jaipur | 28 | 0.91 | 2.56 | 2.90 | 1.59 | 0.20 | 7.24 |
| Kolkata | too few years | | | | 5.37 | 0.41 | 8.38 |

A single normal week already scores well above 0.2 in every city. The lockdown is higher in most
cities, but the two overlap, and Hyderabad shows no separation at all (0 of 13 lockdown weeks
above its normal 90th percentile). In a separate check of one week only (1 to 7 April 2019 as the live window, with references
built from 2016-2018), the same-season reference
helped Delhi (PSI 0.42 against all seasons, 0.07 against the same season) and Lucknow (1.02 and
0.19), and did not help Chennai (0.47 and 0.69) or Jaipur (1.31 and 1.28). Bengaluru fell from
3.55 to 1.66, which is still far above 0.2.

Two reasons I can name: a week of PM2.5 values is strongly correlated hour to hour, so 10 bins
are too fine for it, and the network of stations changed between years (Bengaluru went from 2 to
8 stations in 2018). So a fixed PSI threshold of 0.2 does not work for a one-week window. This is
the main open point for Stage 11.
