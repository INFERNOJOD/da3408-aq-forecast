# Progress Report

This file records what I built, how to run it, what I measured, and what went wrong along the way. Part 1 covers Stages 2-4. Part 2 covers the housekeeping, Stage 5 and Stage 5b.

## Part 1: Stages 2, 3 and 4

All three stages are done and committed. Nothing is blocked. I used no sudo and pushed nothing to any remote except the local DVC folder. The `a4-*` containers kept running, and `data/raw` was never touched.

| Stage | Commit | What it delivers |
|-------|--------|------------------|
| 2. Project skeleton | `6f8ca82` | Python 3.12 environment, lint and test setup, shared helpers |
| 3. DVC | `1de6eed` | Raw data versioned by DVC with a local remote |
| 4. Spark ingest | `2491249` | CSV files converted to Parquet, with run records |

At the end of Part 1, `ruff check` passed, `pytest` gave 29 passed and 0 failed, and `dvc status` said up to date.

### Stage 2: project skeleton

I made a Python 3.12 virtual environment in `.venv` with `uv`. The VM ships Python 3.14, which is too new for Spark and MLflow. `pyproject.toml` holds the package list and the ruff and pytest settings. `params.yaml` is the one place for settings such as Spark memory, the city list and the cut-off date. `.env.example` is a template for secrets, and the real `.env` is git-ignored.

`src/common/` has three small modules: `config.py` loads `params.yaml` and `.env`, `logging_setup.py` configures logging the same way everywhere, and `errors.py` defines the project's own error types. Every later stage needs the same logging, settings and error handling, so I wrote them once.

### Stage 3: DVC

I started DVC in the repo. Its remote is a plain folder, `/home/krish-yadav/DA3408/dvc-remote`, so nothing touches a cloud. `data/raw` is tracked by DVC, and git stores only the small `data/raw.dvc` file, which holds a hash of the data. I pushed the raw data to the remote.

Git is bad at big files. DVC keeps the data outside git and pins the exact version by hash, so a git commit points to the exact data it used.

This stage had a problem. I had a broad `/data/*` rule in `.gitignore`, and DVC silently skipped `data/raw.dvc`. `dvc push` said "up to date" while the remote was empty. It took a while to find, because nothing reported an error. I replaced the rule with the sub-folders `/data/raw/`, `/data/interim/` and `/data/features/`, and `dvc push` then sent all the files.

### Stage 4: Spark ingest

`src/pipeline/ingest.py` reads the 5 CSV files with Spark and writes them as Parquet into `data/interim/`. Each column has a fixed type set in code, so a bad value stops the run instead of causing silent errors. After writing, the stage counts the CSV rows with plain Python and compares them with the Parquet row count. They must match.

`src/common/stage_runner.py` wraps any stage. It records time, row count, rows per second, status and error message in `reports/runs.jsonl`, and pushes the numbers to the Pushgateway if `PUSHGATEWAY_URL` is set. If that server is down, the pipeline keeps going. The pipeline console will read the file later. `src/common/spark.py` starts Spark with the memory limits (driver memory and 8 shuffle partitions; the driver was 3 GB when I wrote this stage and is 2 GB now, see Part 3). `dvc.yaml` got its first stage, `ingest`, and I updated the ingest row of `docs/LLD.md` to match the real inputs and outputs.

I chose Parquet because it is compressed and stored by column, so later stages read only the columns they need.

### How to run Part 1

```bash
cd /home/krish-yadav/DA3408/da3408-project-aq-forecast
source .venv/bin/activate

ruff check . && pytest -q          # lint + 29 tests (about 5 s)
dvc repro                          # runs ingest (about 8 s); skips if nothing changed
dvc dag                            # shows the pipeline graph
dvc status -c                      # data and remote in sync?
cat reports/stage_metrics/ingest.json   # last run's numbers
```

To restore the raw data on a fresh checkout, run `dvc pull`.

### Measured numbers for ingest

The full table is in `docs/metrics.md`.

| What | Value |
|------|-------|
| Rows ingested | 3,434,754 (5 tables) |
| Stage time | 8.0 to 8.4 s (3 runs) |
| Throughput | about 410,000 to 430,000 rows/sec |
| Disk size | CSV 283 MB, Parquet 65 MB |
| Peak Spark memory | about 1.2 GB (limit 3 GB) |

### Things to know from Part 1

Spark runs in UTC so that timestamps keep the wall-clock values from the CSV, which are in IST. I never convert them. This caught me out once: Python's `collect()` shifts times to the machine's own time zone, and a test showed hours that were off. I now use Spark functions like `hour()` in tests.

`reports/runs.jsonl` is git-ignored, because it is runtime data that the backend will read. The `git_commit` in a run record is the commit that was current when the stage ran, so a run made before a commit shows the older hash. Free RAM on the VM is only about 3.9 GB, so heavier Spark stages should run alone. MLflow, Docker, Prometheus, Grafana, FastAPI and Streamlit are not built yet.

### Viva questions for Part 1

**1. Why Parquet instead of reading the CSV every time?**
Parquet is columnar and compressed. My data shrank from 283 MB to 65 MB. Later stages read only the columns they need, and the types are already fixed, so no text parsing is repeated.

**2. Why DVC and not Git LFS?**
DVC also records the pipeline: stages, inputs, outputs and parameters, in `dvc.yaml` and `dvc.lock`. It re-runs only what changed, and it works with a plain local folder as storage, so no cloud is needed. Git LFS only stores large files.

**3. How do you know the ingest did not lose rows?**
There are two checks. Spark reads with FAILFAST, so a malformed row stops the run. Then the stage counts CSV lines with plain Python and compares that with the Parquet row count. For all 5 tables they matched (3,434,754 rows).

**4. What happens if a stage fails or the monitoring server is down?**
`run_stage` catches the error, writes a "failed" record with the message to `runs.jsonl`, and raises a clear error. The pipeline console will show it. If the Pushgateway is down, a warning is logged and the pipeline still runs, because a monitoring outage should not stop data work.

**5. Why local Spark with 2 GB and 8 partitions?**
The VM has 8 GB RAM and 4 cores. Spark's default of 200 shuffle partitions creates many tiny tasks, which is slow on this small data. 8 partitions is about 2 per core. I started with a 3 GB driver to leave room for the OS and Docker, and the measured peak was 1.2 GB. I later lowered it to 2 GB (see Part 3).

---

## Part 2: housekeeping, Stage 5 (validate) and Stage 5b (EDA)

This part is also done and committed, and nothing is blocked. I used no sudo, pushed nothing except to the local DVC folder, and left `data/raw` and the `a4-*` containers alone. At the end `ruff check` passed, `pytest` gave 60 passed and 0 failed, and `dvc status` said up to date.

| Work | Commit | What it delivers |
|------|--------|------------------|
| Housekeeping and benchmark | `d5b11f2` | Empty folders removed, status column in `docs/PLAN.md`, pandas vs Spark benchmark |
| Stage 5: validate | `040e474` | 48 data checks, `reports/validation.json`, second DVC stage |
| Stage 5b: EDA | `ed7b6bd` | 8 CSV aggregates, 6 figures, `docs/eda.md` with 9 data biases |

### Housekeeping

I deleted the empty `backend/`, `frontend/`, `pipeline/` and `notebooks/` folders, and added a Status column to `docs/PLAN.md` that shows "Done" and the commit hash for finished stages.

I also benchmarked pandas against Spark on the same ingest job. The result went against Spark. Pandas took about 3.7 s and Spark about 8.2 s, so pandas was about twice as fast. The data is only 283 MB and fits in memory, and Spark pays about 1.2 s to start plus the cost of planning each job. Both gave the same row counts. I am keeping Spark because the course requires it and because it can handle data larger than memory. I have not tested that second reason, so it is a design argument and not a measured result. The numbers are in `docs/metrics.md`.

### Stage 5: validate

`src/pipeline/validate.py` has two parts. Spark collects plain numbers (counts, minimums, maximums) in one pass per table. Then ordinary Python functions turn those numbers into pass, warn or fail results. The second part needs no Spark, so its tests are fast.

Hard failures stop the pipeline: wrong columns or types, an empty table, missing ids or times, duplicate rows, negative values, values above the sensor ceiling, times outside 2015-2020, timestamps not on the hour, duplicate station ids, and any selected city that is short of data or missing from the replay period. Warnings are only reported: unknown AQI bucket names, too much missing PM2.5, and unknown station ids. The limits live in `params.yaml` under `validate:`, and a second stage in `dvc.yaml` runs the check.

`reports/validation.json` is written even when validation fails, so I can inspect the failure. The error message names the column, the limit and the row count, for example `PM2.5 > 1000 in 12 rows`.

On the real data all 48 checks pass, with 0 warnings and 0 failures. The data is clean: no duplicates, no negatives, no missing ids. All 7 selected cities have PM2.5 for 99.9% to 100% of the 2,352 replay hours. I wanted this stage because bad data would otherwise flow into training silently, and a hard stop with a clear reason is exactly what the pipeline console should show.

### Stage 5b: EDA and data biases

`src/pipeline/eda.py` runs Spark counts and saves them as 8 small CSV files in `reports/eda/`. `scripts/plot_eda.py` draws 6 figures into `docs/img/`. `docs/eda.md` explains the findings, lists 9 data biases with evidence and what I do about each, and gives a text table for every figure. EDA is not a DVC stage. I run it by hand, so the 7-stage DAG stays as CLAUDE.md requires.

The five main findings:

1. Missing data is concentrated in 2015-2017 and in some cities. The 7 selected cities have no PM2.5 gaps in 2019-2020.
2. The yearly cycle is strong in the north. Delhi is 5.5x higher in November than in August, while the south is flat and low.
3. Part of the lockdown drop is just the season. Comparing the same dates of 2019 gives a fair drop of 25-52%. My first, naive before-and-after comparison overstated it by 9-23 points in four cities.
4. The monitoring network grew (Delhi from 10 to 37 stations), so city averages are not fully comparable across years.
5. Extreme PM2.5 hours (250 or more) are rare outside Delhi, Lucknow and Kolkata, and almost absent in the lockdown period.

### How to run Part 2

```bash
source .venv/bin/activate
ruff check . && pytest -q                    # 60 tests (about 16 s)
dvc repro                                    # ingest + validate (validate about 32 s)
cat reports/validation.json | head -20       # the check report
python -m src.pipeline.eda                   # EDA CSVs (about 10 s)
python scripts/plot_eda.py                   # figures into docs/img/
python scripts/bench_pandas_ingest.py 3      # the pandas benchmark
```

### Measured numbers for Part 2

The full tables are in `docs/metrics.md`.

| What | Value |
|------|-------|
| Validate time | 32.1 to 33.5 s over 4 runs, about 105,000 rows/s |
| Validate peak memory | about 3.4 GB with the 3 GB driver; about 1.4 GB with a 1 GB driver (same answer, 34.2 s) |
| Pandas vs Spark ingest | 3.4 to 3.9 s vs 8.0 to 8.4 s |
| EDA aggregates | about 9.4 s, 1,528 rows in 8 files |

### Things to know from Part 2

**A YAML trap.** An unquoted `NO:` in `params.yaml` is read as the boolean `false`. That crashed validate with `KeyError: 'NO'`, and I lost some time before I saw why. The keys are now quoted, and a test checks that every pollutant has a limit.

**Memory.** The 3.4 GB peak is the JVM filling the heap it is allowed, not a real need. The 1 GB run proves it: same answer, almost the same time. I kept the 3 GB limit from CLAUDE.md at that point. Free RAM on the VM is only about 3.9 GB, so I run Spark stages alone.

**No Node.js.** I could not run the palette validator script that comes with the chart guidance. I used the first seven slots of its documented palette in the documented order, which the guidance says passes the adjacent-pair checks. I did not verify that myself. Every figure also has a text table, so colour is never the only channel.

**Drift will be partly seasonal.** Because of finding 3, the PSI drift signal in Stage 11 will react to the season as well as to the lockdown. `docs/eda.md` says so, and I left the design in `docs/HLD.md` unchanged. At Stage 11 I need to decide whether to keep it as it is or add a seasonal reference.

**City selection.** I picked the 7 cities for long history and a low missing share. Gurugram, Patna and Ahmedabad have more data than Kolkata or Jaipur but I left them out because 15-35% of their PM2.5 is missing. This is bias 1 in `docs/eda.md`.

I also updated `docs/LLD.md` for the validate stage inputs and the EDA files.

### Viva questions for Part 2

**1. Why validate data in its own stage, and what stops the pipeline?**
So bad data cannot reach training silently. The stage computes 48 checks and splits them into hard failures (schema, duplicates, negative values, values above the sensor ceiling, missing ids, too little data in the selected cities) and warnings. Any hard failure stops the pipeline with a message like `PM2.5 > 1000 in 12 rows`, and the failure appears in `runs.jsonl` and later in the console. The report is still saved.

**2. Why split validate into Spark profiling and pure Python checks?**
Spark does what it is good at, counting over millions of rows in one pass. The decision logic is plain Python on a small dictionary, so it is fast to unit-test without starting Spark and easy to read. It also matches the functional style stated in the HLD.

**3. Pandas was faster than Spark in your benchmark. Why use Spark?**
On 283 MB that fits in memory, pandas is about 2x faster, because Spark pays for JVM start and job planning. I use Spark because the course requires it as the data engine, and because it works on data larger than memory with the same code. I did not measure large data, so I call that a design argument and not a result.

**4. The lockdown caused a big drop in PM2.5. How sure are you of its size?**
Less sure than the naive numbers suggest. Comparing before and after 25 March gives 30-75% drops, but April to June is naturally cleaner than January to March. Comparing the same dates of 2019 gives 25-52%. The effect is real in all 7 cities but smaller than it first looks, so the drift alarms will partly be seasonal. I say this openly in `docs/eda.md`.

**5. What data biases did you find, and what did you do about them?**
Nine, listed in `docs/eda.md`. The main ones: missing data is concentrated in early years and some cities, so I do not make up values. The station network grew (Delhi 10 to 37), so city averages are not comparable across years, and I trust 2018 onwards most. Extreme hours are rare outside the north, so the model will under-predict peaks and I report high-value error separately. And I only model 7 cities, so the app only offers those.

---

## Part 3: Spark driver memory lowered to 2 GB

I changed the driver memory from 3g to 2g in `CLAUDE.md` and `params.yaml`. The default in `src/common/spark.py`, one test, `docs/HLD.md` and `docs/PLAN.md` changed with it.

The reason is the VM. Only about 3.9 GB is free, and the validate stage with a 3 GB driver grew to 3.4 GB of JVM memory. The earlier 1 GB test gave the same answer in almost the same time, so the extra memory was not doing useful work. With 2g, `dvc repro` ran both stages again with the same results: ingest 8.9 s, validate 33.3 s, and a peak of about 2.4 GB of JVM memory. The old numbers in `docs/metrics.md` stay as they were, labelled with the driver size they were measured with.

In `docs/HLD.md` the planned batch container limit drops from 3.5g to 2.5g, and the planned total during a retrain from about 6.1 GB to about 4.9 GB. While rechecking that table I found the old 6.1 GB did not match its own parts (serve without frontend and Grafana is 2,368 MB, plus 3,584 MB is about 5.9 GB), so I fixed the arithmetic too. These are still planned figures. I measure real usage in Stage 13.

I did not know whether the features stage would fit in 2g. It does (see Part 4).

---

## Part 4: Stage 6, Spark features

Stage 6 is done and committed as `cea9532`. Nothing is blocked. At the end `ruff check` passed, `pytest` gave 77 passed and 0 failed, and `dvc status` said up to date. As before I used no sudo, pushed nothing except to the local DVC folder, and left `data/raw` and the `a4-*` containers alone.

### What I built

`src/pipeline/features.py` turns the hourly city data into one row per selected city and hour, with the model inputs and the two targets. It writes `data/features/train.parquet`, `data/features/serving.parquet` and `reports/baseline_stats.json`. The input and target column names live in one file, `src/common/schema.py`, and a test checks that this list equals the table in `docs/LLD.md`. So the code and the design document cannot drift apart without a test failing.

The stage is a chain of small functions, each taking a Spark DataFrame and returning one. Only `run_features` reads and writes files.

I made four decisions that matter for correctness.

**Lags count hours, not rows.** If an hour were missing from the source, a row-based lag of 24 would reach back more than 24 hours. So I first build a complete hourly grid per city, with null values for any missing hour, and take the lags on that grid. I assumed the source had such holes. When I checked at the end, it does not: none of the 7 selected cities has a single absent hourly row, and gaps in this data are null values, not missing rows. On this dataset the grid changes nothing. I kept it because retraining will see new data, and a hole there would shift every lag silently. A unit test covers a missing hour.

**Short gaps are forward-filled, only for inputs.** A gap of up to 3 hours is filled with the last seen value. A longer gap stays null. Targets are never filled. A missing target stays missing, and the training stage drops it. I do not want the model to learn from numbers I invented.

**Nothing from the future.** Every feature at hour t uses hour t and earlier. In the training file I also null any target that falls after the cutoff. A row at 23:00 on 24 March has no 24-hour target, because that hour is after the cutoff. Without this, the last day of training would quietly contain a target from the replay period.

**Features only run after validation has passed.** More on this under "What went wrong".

The serving file holds every hour from 2020-01-01 to 2020-06-30 for the 7 cities (4,368 per city). The backend will use it for the replay. It includes the actual values, and the backend reveals them only when its replay clock passes them.

The baseline file describes `pm25_lag_1` per city on the training rows. It stores 10 quantile bins and the share of rows in each. Stage 11 will compare live data against it with PSI.

### How I checked it

Unit tests cover the grid, lags across a gap, the forward-fill limit, targets, rolling windows, calendar features, the cutoff, the serving slice and the baseline. One test changes a later reading and checks that no earlier feature row changes. That is the test I trust most for leaks.

I also did a stronger check outside the test suite. I recomputed every feature column in pandas, with plain `shift` and `rolling`, for Hyderabad (7% of its PM2.5 values are missing) and Kolkata (which starts late). Each city had 4,368 serving rows and 21 columns, and there were 0 mismatches. In the training file no row has a target from after the cutoff.

### What went wrong

**The DAG did not enforce the order.** When I ran `dvc dag`, `validate` and `features` both hung off `ingest` side by side. So a failed validation would not have stopped features from running, which defeats the point of the validate stage and goes against the `ingest -> validate -> features` chain in CLAUDE.md. I fixed it twice over. `features` now depends on `reports/validation.json` in `dvc.yaml`, and the stage itself refuses to run unless that report says "passed". The second part protects a direct `python -m src.pipeline.features` run too. A test covers a missing, failed and unreadable report.

**The time zone caught me again.** My first test helper converted the start time with Python's `timestamp()`, which uses the machine's local time zone (IST). Every hour index came out shifted by six, and 7 tests failed. The stage was right and the test was wrong. I now compute the index inside Spark. Two more failures were plain mistakes in my expectations: I asked for a lag that reached before the start of the series, and for an hour past the end of it.

**PM10 is mostly missing.** In the training rows, `pm10_lag_1` is null 40% of the time. The other co-pollutants are 2-5% null and the PM2.5 lags about 6%. LightGBM handles nulls, but Ridge does not, so the training stage will have to fill them for Ridge. I will handle that in Stage 7. I did not drop PM10, because the LLD fixes the input list.

### Memory at 2g

The whole pipeline (`ingest`, `validate`, `features`) runs on the 2 GB driver. Peak JVM memory was about 2.5 GB for the full run, and about 4.9 GB of the VM's RAM was available afterwards. The 2g limit is not a problem so far.

### How to run

```bash
source .venv/bin/activate
ruff check . && pytest -q                 # 77 tests (about 26 s)
dvc repro                                 # runs only the stages that changed
dvc dag                                   # ingest -> validate -> features
python -m src.pipeline.features           # run the stage by itself (about 12 s)
cat reports/baseline_stats.json | head -20
```

### Measured numbers

The full table is in `docs/metrics.md`.

| What | Value |
|------|-------|
| Training rows | 270,612 |
| Serving rows | 30,576 |
| Features stage time (5 runs) | 11.8 to 13.0 s |
| Whole pipeline from a clean state | ingest 8.8 s + validate 32.9 s + features 13.0 s |
| Peak Spark memory, driver 2g | about 2.5 GB (JVM, whole run) |

### Things to know

The baseline bins use training rows from 2015 up to the cutoff, so they mix all seasons. The drift check in Stage 11 will therefore see part seasonal change as drift. I described this in `docs/eda.md`, and I still need to decide at Stage 11 whether to keep it.

I changed `docs/LLD.md` for the new files and for the features stage inputs. I also changed the Stage 6 row in `docs/PLAN.md`. It described an older train/holdout split by year, and the build follows the `cutoff` design from `docs/HLD.md`.

### Viva questions for Stage 6

**1. Why build a complete hourly grid before computing lags?**
Because a row-based lag is only right if no hour is missing. On the grid, "24 rows back" is exactly 24 hours back, even if a row is absent. I should be honest that on this dataset it changes nothing: I checked, and none of the selected cities has an absent hourly row. Its gaps are null values. The grid is a safeguard for new data at retraining time.

**2. How do you know the features do not leak the future?**
Three ways. Every window and lag looks backwards only. A unit test changes a later reading and checks that every earlier feature row stays the same. And I recomputed all feature columns in pandas for two cities and found 0 mismatches. For training I also hide any target that lies after the cutoff.

**3. Why forward-fill only up to 3 hours, and only for inputs?**
A short gap is probably a sensor hiccup, and carrying the last value is a fair guess for an input. A long gap is real missing data, so I leave it null. I never fill targets, because the model would then learn to predict my own guess. The 3-hour limit is a setting in `params.yaml`.

**4. What stops the pipeline from building features on bad data?**
The `features` stage depends on `reports/validation.json`, so `dvc repro` runs validate first. The stage also reads that report itself and refuses to run unless the status is "passed". I added this after seeing that the first version of the DAG did not enforce the order.

**5. What is in the drift baseline, and how is it used?**
For each city it stores the quantile bin edges of `pm25_lag_1` on the training rows and the share of rows in each bin. At Stage 11 I bin the last 168 live hours with the same edges and compare the shares to the baseline with PSI. A PSI above 0.2 means a clear shift. The weakness is that the baseline mixes seasons, so a seasonal change can look like drift.
