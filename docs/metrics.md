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

### Stage 7 update: 90-day half-life

The sections above describe the first run, with a 30-day half-life. I then changed the
half-life to 90 days (everything else unchanged, deterministic training). Same evaluation
window and rows: 497 at 1 h and 336 at 24 h. Mean absolute error in µg/m³:

| Model | 1 h, 30 days | 1 h, 90 days | 24 h, 30 days | 24 h, 90 days |
|-------|-----:|-----:|-----:|-----:|
| Persistence | 5.13 | 5.13 | 14.70 | 14.70 |
| Seasonal naive | 15.49 | 15.49 | 14.70 | 14.70 |
| Ridge | 5.31 | 5.03 | 13.83 | 14.25 |
| LightGBM | 4.76 | 4.50 | 14.13 | 13.54 |
| LightGBM / best baseline | 0.927 | 0.894 | 1.022 | 0.950 |

LightGBM is now the best model at both horizons. Its mean over the two horizons is 9.02, against
9.64 for Ridge and 9.92 for persistence, and both ratios are under the limit of 1.02. The
effective number of training rows (see above) rises from 14,542 to 43,518.

Per city, LightGBM against the best baseline on the same rows: better in 5 of 7 cities at 1 h
(worse in Kolkata and Lucknow) and in 4 of 7 at 24 h (worse in Chennai, Kolkata and Lucknow).
These are the same cities as before, with 71 and 48 rows per city. Error on hours with PM2.5 at
or above 121: 14.7 on 13 hours at 1 h and 61.2 on 10 hours at 24 h. The training stage takes
23.4 s.

## Stage 8: evaluate, test, register (no Spark)

Measured with `dvc repro` on the same data as Stage 7. The three stages are small because they
score about 830 rows and write a few JSON files.

| Stage | Time | Rows | What it does |
|-------|-----:|-----:|--------------|
| train | 25.9 s | 505,852 | unchanged work, now also saves the chosen model per horizon |
| evaluate | 0.7 s | 833 (497 at 1 h, 336 at 24 h) | loads the candidate (and the champion, if there is one) as MLflow packages and scores them |
| test | under 0.1 s | 1 | applies the promotion rule |
| register | 0.4 to 0.6 s | 1 | creates a registry version and moves the aliases, or tags the run as rejected |

Scoring through the package gives the same errors as the train stage within rounding (the package
rounds predictions to 2 decimals): mean MAE 9.0180 against 9.0180, per horizon 4.4995 against
4.4996 at 1 h and 13.5365 against 13.5364 at 24 h. LightGBM is served at both horizons.

## Stage 9: model server

Measured on this VM (4 CPU, ARM64) with the container `aq-model-server` run with `--memory 1g`, serving champion v1 (LightGBM at both horizons). The client was a Python loop on the host calling through the proxy (port 5001 inside the container), one request at a time, 300 requests per row. This is serial latency, not a load test.

| Request | p50 | p95 | p99 | Throughput (serial) |
|---------|----:|----:|----:|--------------------:|
| 1 row | 4.9 ms | 8.1 ms | 9.6 ms | 188 req/s |
| 14 rows (7 cities x 2 horizons, what the backend sends) | 6.5 ms | 9.9 ms | 12.5 ms | 141 req/s |

The same test outside Docker gave 4.7 ms p50 for 1 row and 6.1 ms p50 for 14 rows, so the container adds no visible cost.

| Item | Value |
|------|------:|
| Time from the proxy start to "Serving champion v1" in the log (package download and model load) | 3 s |
| Memory of the container after the tests | 504 MiB (of the 1 GiB limit) |
| Image size | 291 MB |
| Requests that failed while the champion was swapped (about 25 s of requests every 50 ms, run outside Docker) | 0 |

During a swap two MLflow processes exist for a few seconds, so memory briefly rises above the 504 MiB. I did not measure that peak, and I will set the compose `mem_limit` in Stage 13 with that in mind.

## Stage 10: backend

Measured on this VM with the backend running locally (plain HTTP, one uvicorn worker) in front of the real model server on the same machine, serving champion v1. The client was a Python loop on the host with one request at a time, 200 requests per endpoint. This is serial latency, not a load test, and I did not measure the backend's memory.

| Endpoint | p50 | p95 |
|----------|-----|-----|
| `GET /forecast?city=Delhi` (two model rows, one call to the model server) | 8.7 ms | 15.6 ms |
| `GET /health` (includes a `/ping` to the model server) | 1.8 ms | 3.4 ms |
| `GET /cities` | 0.5 ms | 1.2 ms |

A forecast includes the feature lookup, one call to the model server and the registry cache. The model server alone took 6.5 ms at p50 for 14 rows in Stage 9, so most of the 8.7 ms is the model call. The replay clock ran at 20 simulated hours per second and reached 2020-03-27 12:00 after 3 seconds, as expected.

| Test run | Count |
|----------|-------|
| Backend tests (`tests/test_backend.py`) | 92 passed |
| Whole suite | 248 passed, 0 failed |

## Stage 11: drift detection and automated retraining

### Per-city PSI thresholds

Written by the features stage to `reports/drift_thresholds.json`. Each value is the 95th percentile
of the leave-one-year-out PSI of `pm25_lag_1` over blocks 1 to 13 of every reference year (168 h
windows, 10 bins, empty bins counted as 0.0001). Kolkata has only 2018-2019 and does not vote.

| City | Threshold | Normal weeks scored | Reference years |
|------|----:|----:|------|
| Delhi | 2.031 | 52 | 2016-2019 |
| Bengaluru | 2.041 | 46 | 2016-2019 |
| Lucknow | 2.507 | 48 | 2016-2019 |
| Jaipur | 2.748 | 28 | 2017-2019 |
| Hyderabad | 3.586 | 52 | 2016-2019 |
| Chennai | 5.203 | 50 | 2016-2019 |

Computing them did not make the features stage measurably slower: it took 12.0 s, inside the
11.8-13.0 s range of Stage 6. That `dvc repro` (features to register, original cutoff) took
42.3 s, and the candidate was rejected because its mean MAE equalled the champion's (9.018).

### Why the first rule failed

The rule in the HLD before Stage 11: at least 3 cities above threshold **and** a pooled 72 h MAE
ratio above 1.5 (champion v1, eval-window 1 h MAE 4.4995). I scored every hour from the first full
window (replay hour 167) to the end, 2,185 hours per year. A normal year is scored against a
reference built from the other years only. These counts come from a one-off check that reuses
`scripts/replay.py`.

| Year | PSI: ≥ 3 cities | MAE ratio > 1.5 | Both (old rule) |
|------|----:|----:|----:|
| 2016 | 0 h | 2,184 h | 0 h |
| 2017 | 0 h | 1,840 h | 0 h |
| 2018 | 14 h | 1,949 h | **13 h** (false alarm) |
| 2019 | 44 h | 675 h | 0 h |
| 2020 lockdown | 874 h | **0 h** | **0 h** (never fires) |

The pooled 72 h MAE ratio of champion v1, from `python -m scripts.replay --with-mae`:

| Year | median | 95th percentile | max |
|------|----:|----:|----:|
| 2016 | 2.31 | 6.00 | 14.68 |
| 2017 | 2.53 | 5.38 | 6.83 |
| 2018 | 2.04 | 3.42 | 4.14 |
| 2019 | 1.36 | 1.86 | 2.17 |
| 2020 lockdown | 0.88 | 1.16 | 1.47 |

The model's error follows the PM2.5 level. Mean 1 h absolute error of v1 over the replay window,
by year (2016-2019 are inside the training data, so these are in-sample and flattering):

| City | 2016 | 2017 | 2018 | 2019 | 2020 | Mean PM2.5 2019 | Mean PM2.5 2020 |
|------|----:|----:|----:|----:|----:|----:|----:|
| Delhi | 13.60 | 20.84 | 8.43 | 6.40 | 4.74 | 79.3 | 47.9 |
| Lucknow | 18.02 | 15.21 | 16.88 | 11.17 | 6.61 | 88.9 | 52.6 |
| Chennai | 7.96 | 14.32 | 11.11 | 10.00 | 5.25 | 42.6 | 21.8 |
| Jaipur | — | 9.05 | 9.47 | 5.58 | 4.94 | 51.3 | 33.7 |
| Bengaluru | 8.11 | 5.40 | 10.14 | 4.59 | 2.78 | 38.8 | 21.8 |
| Hyderabad | 15.29 | 4.76 | 2.77 | 2.98 | 2.40 | 35.8 | 26.9 |
| Kolkata | — | — | 4.31 | 3.47 | 1.67 | 41.2 | 19.9 |

Relative to persistence the model also does not get worse in 2020 (model MAE / persistence MAE
between 0.87 and 1.04 per city). The fallbacks I had planned do not help: with 2 cities the PSI
condition holds for 17 to 209 hours in each normal year, and removing Hyderabad changes almost
nothing, while the MAE condition still blocks the lockdown in both cases.

### Acceptance test with the rule in use (PSI only, at least 4 of 6 cities)

`python -m scripts.replay` → `reports/drift_replay.json`, exit code 0. Runtime 3.8 s including
loading the champion for the MAE part. Hours with at least k voting cities above threshold:

| Year | Voting cities | k ≥ 2 | k ≥ 3 | k ≥ 4 (drift) | k ≥ 5 | Episodes | First drift |
|------|----:|----:|----:|----:|----:|----:|------|
| 2016 | 5 | 136 | 0 | 0 | 0 | 0 | — |
| 2017 | 6 | 17 | 0 | 0 | 0 | 0 | — |
| 2018 | 6 | 100 | 14 | 0 | 0 | 0 | — |
| 2019 | 6 | 209 | 44 | 0 | 0 | 0 | — |
| 2020 lockdown | 6 | 1,217 | 874 | **661** | 249 | 5 | 2020-03-31 23:00 |

Result: **passed**. The lockdown triggers drift for 661 of 2,185 hours, and normal weeks trigger
it for 0 hours. The lockdown episodes: 31 Mar 23:00 - 4 Apr 21:00 (95 h), 6-7 Apr (46 h),
9-11 Apr (49 h), 13-14 Apr (11 h) and 24 Apr - 13 May (460 h). The largest number of cities above
threshold at once in a normal year is 3, so the margin is zero. Hours each city was above its
threshold during the lockdown: Delhi 1,258, Lucknow 1,239, Jaipur 1,028, Bengaluru 768, Chennai
597, Hyderabad 1. Hyderabad almost never votes for drift, as the Stage 6 check predicted.

### End-to-end run: drift → alert → retrain → promotion → new model served

Run on this VM without Docker for the Python services: model server, backend (replay at 0.5
simulated hours per second), ops runner, and Prometheus v3.5.0 and Alertmanager v0.28.1 in their
own containers (ports 19090 and 19093, scrape and evaluation every 15 s). Frontend and Grafana
were not running.

| Wall clock | Event |
|------|------|
| 17:13:09 | Replay started at sim time 2020-03-25 00:00 |
| ≈ 17:18:43 | Sim time 2020-03-31 23:00: 4 cities above threshold, `aq_drift_detected` = 1 |
| 17:19:09 | `PM25DriftHigh` pending |
| 17:20:09 | `PM25DriftHigh` firing (after `for: 1m`) |
| 17:20:13 | Alertmanager webhook → backend wrote `rt-20261020-172013` (cutoff 2020-04-02 19:00, drift snapshot: 4 cities, PSI max 6.07, MAE ratio 0.83) |
| 17:20:22 | Runner started pipeline run `20261020-172022`, cutoff moved from 2020-03-24 23:00 to 2020-04-02 19:00 |
| 17:21:30 | Gate passed, v4 registered as champion, model server swapped to v4, smoke check passed |

Drift to new champion in service: about 2 min 47 s, of which the alert's `for: 1m` and the
scrape and evaluation steps took about 1.5 min.

| Stage (run `20261020-172022`) | Duration | Rows out | Rows/s |
|------|----:|----:|----:|
| features | 12.2 s | 302,672 | 24,754 |
| train | 24.5 s | 508,818 | 20,791 |
| evaluate | 0.6 s | 833 | 1,424 |
| test | 0.0 s | 1 | — |
| register | 0.3 s | 1 | 3.0 |

ingest and validate did not change, so DVC skipped them. Promotion decision on the window
2020-03-30 20:00 to 2020-04-02 19:00 (497 rows at 1 h, 336 at 24 h, all inside the lockdown):

| | 1 h MAE | 24 h MAE | Mean |
|------|----:|----:|----:|
| Candidate (LightGBM, both horizons) | 3.54 | 9.39 | 6.467 |
| Champion v1 | 3.70 | 9.80 | 6.750 |
| Best baseline | 4.02 (persistence) | 10.55 (Ridge) | |

The candidate is 0.881 and 0.890 times the best baseline (limit 1.02) and beats v1, so it became
v4 (versions 2 and 3 do not exist in the registry; MLflow does not reuse numbers). The MLflow run
`498b149f…` is tagged `trigger=drift_alert`, `cutoff=2020-04-02 19:00:00`, `git_commit=b2eff79`
and `git_dirty=true` (the runner changed `cutoff` in `params.yaml`), and has the metrics
`drift_cities_exceeding` 4, `drift_psi_max` 6.073 and `drift_mae_ratio_pooled` 0.827. After the
swap, `/forecast?city=Delhi` answered with version 4 and commit `b2eff79`.

Memory over the whole run, sampled every 2 s with `free -m` (the whole VM, which also ran three
unrelated containers): peak used 5,008 MB, lowest available 2,389 MB.

The auto-rollback path (smoke check fails, so the runner moves `champion` back) is covered by unit
tests only. I did not make a real model fail.

| Test run | Count |
|----------|-------|
| New tests (`test_drift`, `test_backend_drift`, `test_ops_runner`, `test_replay_script`, 2 in `test_features`) | 45 |
| Whole suite | 293 passed, 0 failed |
