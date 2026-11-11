# Progress Report

This file records what I built, how to run it, what I measured, and what went wrong along the way. Part 1 covers Stages 2-4. Part 2 covers the housekeeping, Stage 5 and Stage 5b.

## Part 1: Stages 2, 3 and 4

All three stages are done and committed. Nothing is blocked. I used no sudo and pushed nothing to any remote except the local DVC folder. The `a4-*` containers kept running, and `data/raw` was never touched.

| Stage | Commit | What it delivers |
|-------|--------|------------------|
| 2. Project skeleton | `1022dee` | Python 3.12 environment, lint and test setup, shared helpers |
| 3. DVC | `9025b49` | Raw data versioned by DVC with a local remote |
| 4. Spark ingest | `d3228c4` | CSV files converted to Parquet, with run records |

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
| Housekeeping and benchmark | `a200228` | Empty folders removed, status column in `docs/PLAN.md`, pandas vs Spark benchmark |
| Stage 5: validate | `c82c9e0` | 48 data checks, `reports/validation.json`, second DVC stage |
| Stage 5b: EDA | `fc9f797` | 8 CSV aggregates, 6 figures, `docs/eda.md` with 9 data biases |

### Housekeeping

I deleted the empty `backend/`, `frontend/`, `pipeline/` and `notebooks/` folders, and added a Status column to `docs/PLAN.md` that shows "Done" and the commit hash for finished stages.

I also benchmarked pandas against Spark on the same ingest job. The result went against Spark. Pandas took about 3.7 s and Spark about 8.2 s, so pandas was about twice as fast. The data is only 283 MB and fits in memory, and Spark pays about 1.2 s to start plus the cost of planning each job. Both gave the same row counts. I am keeping Spark because the course requires it and because it can handle data larger than memory. I have not tested that second reason, so it is a design argument and not a measured result. The numbers are in `docs/metrics.md`.

### Stage 5: validate

`src/pipeline/validate.py` has two parts. Spark collects plain numbers (counts, minimums, maximums) in one pass per table. Then ordinary Python functions turn those numbers into pass, warn or fail results. The second part needs no Spark, so its tests are fast.

Hard failures stop the pipeline: wrong columns or types, an empty table, missing ids or times, duplicate rows, negative values, values above the sensor ceiling, times outside 2015-2020, timestamps not on the hour, duplicate station ids, and any selected city that is short of data or missing from the replay period. Warnings are only reported: unknown AQI bucket names, too much missing PM2.5, and unknown station ids. The limits live in `params.yaml` under `validate:`, and a second stage in `dvc.yaml` runs the check.

`reports/validation.json` is written even when validation fails, so I can inspect the failure. The error message names the column, the limit and the row count, for example `PM2.5 > 1000 in 12 rows`.

On the real data all 48 checks pass, with 0 warnings and 0 failures. The data is clean: no duplicates, no negatives, no missing ids. All 7 selected cities have PM2.5 for 99.9% to 100% of the 2,352 replay hours. I wanted this stage because bad data would otherwise flow into training silently, and a hard stop with a clear reason is exactly what the pipeline console should show.

### Stage 5b: EDA and data biases

`src/pipeline/eda.py` runs Spark counts and saves them as 8 small CSV files in `reports/eda/`. `scripts/plot_eda.py` draws 6 figures into `docs/img/`. `docs/eda.md` explains the findings, lists 9 data biases with evidence and what I do about each, and gives a text table for every figure. EDA is not a DVC stage. I run it by hand, so the 7-stage DAG stays as my project brief requires.

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

**Memory.** The 3.4 GB peak is the JVM filling the heap it is allowed, not a real need. The 1 GB run proves it: same answer, almost the same time. I kept the 3 GB limit from my project brief at that point. Free RAM on the VM is only about 3.9 GB, so I run Spark stages alone.

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

I changed the driver memory from 3g to 2g in my project brief and in `params.yaml`. The default in `src/common/spark.py`, one test, `docs/HLD.md` and `docs/PLAN.md` changed with it.

The reason is the VM. Only about 3.9 GB is free, and the validate stage with a 3 GB driver grew to 3.4 GB of JVM memory. The earlier 1 GB test gave the same answer in almost the same time, so the extra memory was not doing useful work. With 2g, `dvc repro` ran both stages again with the same results: ingest 8.9 s, validate 33.3 s, and a peak of about 2.4 GB of JVM memory. The old numbers in `docs/metrics.md` stay as they were, labelled with the driver size they were measured with.

In `docs/HLD.md` the planned batch container limit drops from 3.5g to 2.5g, and the planned total during a retrain from about 6.1 GB to about 4.9 GB. While rechecking that table I found the old 6.1 GB did not match its own parts (serve without frontend and Grafana is 2,368 MB, plus 3,584 MB is about 5.9 GB), so I fixed the arithmetic too. These are still planned figures. I measure real usage in Stage 13.

I did not know whether the features stage would fit in 2g. It does (see Part 4).

---

## Part 4: Stage 6, Spark features

Stage 6 is done and committed as `4fa51a0`. Nothing is blocked. At the end `ruff check` passed, `pytest` gave 77 passed and 0 failed, and `dvc status` said up to date. As before I used no sudo, pushed nothing except to the local DVC folder, and left `data/raw` and the `a4-*` containers alone.

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

**The DAG did not enforce the order.** When I ran `dvc dag`, `validate` and `features` both hung off `ingest` side by side. So a failed validation would not have stopped features from running, which defeats the point of the validate stage and goes against the `ingest -> validate -> features` chain in my project brief. I fixed it twice over. `features` now depends on `reports/validation.json` in `dvc.yaml`, and the stage itself refuses to run unless that report says "passed". The second part protects a direct `python -m src.pipeline.features` run too. A test covers a missing, failed and unreadable report.

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

---

## Part 5: your two decisions, and Stage 7 (train)

I applied both decisions and built Stage 7. The code is in commits `ebb05a9`, `eeec08e` and `645bbbd`, and the final run is tagged with the last one. At the end `ruff check` passed and `pytest` gave 117 passed and 0 failed. As before I used no sudo, pushed nothing except to the local DVC folder, and left `data/raw` and the `a4-*` containers alone. Results are in `docs/metrics.md`. This part also lists three open decisions for you; they are at the end of "Open decisions".

### Your two decisions

**PM10 and Ridge.** I kept the PM10 column. Ridge is an sklearn pipeline that starts with a median imputer with a missing-indicator flag for every column that had gaps, then scales the numbers and one-hot encodes city, hour, weekday and month. The imputer is fitted on training rows only and travels inside the pipeline object, so training and scoring treat gaps the same way. LightGBM takes the nulls as they are. A test shows that the flag works: when I made the target higher whenever PM10 was missing, Ridge predicted more than 10 µg/m³ higher for a row with PM10 removed. I wrote this into `docs/HLD.md`. One honest note: Ridge is only a baseline here, so it is scored but never served.

**Same-season drift reference.** The features stage now builds the reference from the same hours of the calendar in 2016-2019. It cuts the replay (25 March to 30 June, 2,352 hours) into 14 blocks of 168 hours and computes decile bins of `pm25_lag_1` for each city and block. A live window whose last hour is replay hour `h` uses block `h // 168`. Years are aligned on 25 March at 00:00, so leap years do not shift the blocks. Kolkata has two reference years and Jaipur three, because they started measuring later. The stage fails if any city and block has fewer than 100 reference values, and it refuses baseline years that reach into the replay year. I updated `docs/HLD.md`, `docs/LLD.md` and `docs/eda.md`.

I then tested whether it works, and the result is not what I hoped. See "Open decisions", point 1.

### What I built in Stage 7

`src/pipeline/train.py` fits Ridge and LightGBM for each horizon (1 h and 24 h). It scores them together with two rule-based baselines, persistence and seasonal naive, on the same evaluation window and the same rows. It then writes one MLflow run and saves the candidate model in `models/candidate/`. The pure parts (splits, weights, models, scores) are in `src/pipeline/modeling.py`, so they are easy to test without MLflow.

Three decisions in the evaluation protocol matter.

**Training rows are purged.** A row only trains if its target hour is before the start of the evaluation window. Otherwise the 24 h target of a late training row would fall inside the window I score on.

**Everything is scored on the same rows.** Rows need the two lags that the naive baselines use. This keeps the comparison fair, at the cost of dropping a few rows.

**Recency weights follow the design.** A row from 30 days before the cutoff counts half as much as a recent one. This is what the HLD says, but it means the model is in practice trained on about 14.5k effective rows out of 253k.

The model is one MLflow pyfunc, `AQForecaster` in `src/pipeline/aq_model.py`, that holds both horizon models and picks one from `horizon_h`. It returns `pm25` and `model_version`. The file imports nothing from the rest of the project. I checked this by copying the saved model to another folder, hiding my source file, and loading it: it predicted correctly. That matters for Stage 9, where the model will run in a container without my source tree.

**What the MLflow run holds beyond autolog.** I do not use autolog at all. The run has these.

- Tags: the full git commit hash, `git_dirty` (true if code or settings differed from the commit, so a hash is only a precise record when it is false; `dvc.lock` and `reports/` are ignored, because the pipeline rewrites them), the DVC hash of the raw data, a hash of the feature values, the cutoff, what triggered the run, and the pipeline run id.
- 88 metrics: MAE and RMSE for all four models, each horizon and each city, the comparison with the best baseline, error on high-pollution hours, fit times, and drift scores when a drift trigger file exists.
- Artifacts: `per_city_mae.csv`, `feature_importance.png`, `residuals.png`, the drift baseline, the resolved settings, and the exact package versions.
- The model, linked to the run, with a signature that matches the LLD columns.

`MLproject` and `python_env.yaml` make the training run the same way everywhere. A test checks that every pinned version in `python_env.yaml` matches `uv.lock`. `mlflow run . -e main --env-manager local` gave the same numbers as the pipeline. I have not tried it with a fresh virtualenv, which would need to download everything again over a slow connection.

### Results

On the 3-day evaluation window, the mean absolute error in µg/m³ is below. The 3-day window has 497 rows at 1 h and 336 at 24 h.

| Model | 1 h | 24 h |
|-------|----:|-----:|
| Persistence | 5.13 | 14.70 |
| Seasonal naive | 15.49 | 14.70 |
| Ridge | 5.31 | 13.83 |
| LightGBM | 4.76 | 14.13 |

At 1 h LightGBM beats the best baseline by 7%. At 24 h it is 2.2% worse than Ridge. With 336 rows that gap is within noise, and a change of half-life or loss function moved it across the line. The model is weaker in Kolkata and Lucknow, and for high-pollution hours (error of 61 on 10 hours at 24 h). The feature importance plot shows what I expected: the 1 h model relies on the current PM2.5 for 54% of its gain, and the 24 h model spreads its reliance across many inputs.

### What went wrong

**The install took about 35 minutes.** The connection to the package index ran at roughly 100 KB/s. My first `uv add` looked stuck and I killed it, then ran `uv sync` in the background. Nothing was broken. I wrote the code and tests while it ran.

**Spark's Python worker did not match.** My new baseline tests failed with "Python in worker has different version (3, 14) than that in driver 3.12". Spark starts its own Python workers, and they used the system Python 3.14. I set `PYSPARK_PYTHON` inside `build_spark`, which fixes it for every stage. The earlier stages never hit this because they never made a DataFrame from a Python list.

**A hard-coded path.** The end-to-end test changes directory, and `data/raw.dvc` was not found. The location now comes from `params.yaml`. The code was wrong to depend on the current directory.

**LightGBM was not repeatable.** The same stage gave 14.20 and then 14.13 at 24 h, with no change in code or data. I tested it: three identical fits differed by up to 5 µg/m³ on a single prediction. With `deterministic` and `force_row_wise` they are identical, and two forced reruns of the stage match. This is now the default in `build_lightgbm`, with a test. Without it, the guideline that every experiment is reproducible would not have held.

**My data fingerprint was not stable.** I first hashed the Parquet files of the features. After rerunning the stage on identical data, the hash was different. Spark puts a random id in every part-file name, and I removed the names from the hash. Then I compared the folder written by the pipeline with a fresh run and the hash still differed. Only 63 of 3.2 million bytes were different, in the file footer, and pandas confirmed that all values were equal. So the byte-level hash cannot work. The version tag now hashes the values themselves, sorted by city and time. The pipeline output and two fresh runs give the same hash, and a test covers file layout, row order and a changed value. This is the sort of thing that would have gone unnoticed, because a tag that is always different looks like a tag that works.

**The dirty flag was wrong in a full pipeline run.** A full `dvc repro` rewrites `dvc.lock` and `reports/validation.json` before the train stage starts, so my first version of `git_dirty` said "true" even though no code had changed. It now ignores those two paths. A test checks that a changed setting still counts.

**`mlflow run` failed twice** because `python` was not on PATH when the virtualenv was not activated. It works after `source .venv/bin/activate`. I left the two failed runs out of the final experiment.

**A sloppy test.** One of my tests used `a == b or c >= 1`, which can never fail. I replaced it with a check that the flag column exists for PM10.

### Open decisions for you

**1. The drift threshold does not work as designed (important for Stage 11).** I tested the same-season reference. A single week of PM2.5, compared with ten decile bins, gives a PSI far above 0.2 even in normal years. In the weeks of 2016-2019 compared with the other years, the median PSI is 0.64 to 1.08 and the 90th percentile 1.8 to 4.1. Lockdown weeks are higher in most cities (median 1.3 to 5.4) but overlap with normal weeks. In Hyderabad no lockdown week stands out. The reference helps in Delhi and Lucknow and does not in the southern cities. So `PSI > 0.2` would fire almost every week. The rolling-MAE signal does not have this problem. I suggest that in Stage 11 I set the PSI threshold per city from the leave-one-year-out values (for example their 95th percentile) and alarm only when several cities exceed it, with the MAE ratio as a second condition. This changes the thresholds in `docs/HLD.md` and the alert rules, so I want your agreement first. The full numbers are in `docs/metrics.md`.

**2. The half-life.** The design says 30 days. In my experiment on a 28-day window, 30 days was the weakest setting at 24 h: about 0.7 µg/m³ worse than 90 or 365 days. On the 3-day window the comparison is mixed. I left it at 30 days. I would change it to 90 days, but it is your design.

**3. The first model and the 1.02 rule.** At 24 h the model is 1.022 times the best baseline, so the Stage 8 promotion rule, applied literally, would block the first model. The comparison rests on 336 rows. The options are to relax the limit for the first model (there is no champion to beat yet), to judge the baseline condition on a longer window, or to accept the block and see what a retrain does. Tell me which, or I will ask again at the start of Stage 8.

I changed one thing without asking you: LightGBM now uses the median (L1) loss, because the models are compared by MAE and it was better or equal in all 8 cells of my test. It is one line in `params.yaml` (`train.lightgbm.objective`).

### How to run

```bash
source .venv/bin/activate
ruff check . && pytest -q                          # 117 tests (about 35 s)
dvc repro                                          # whole pipeline; only changed stages run
python -m src.pipeline.train                       # the train stage alone (about 25 s)
mlflow run . -e main --env-manager local           # the same through MLproject
cat reports/train_metrics.json | head -40          # numbers and versions of the last run
mlflow ui --backend-store-uri sqlite:///mlflow.db  # browse runs at http://127.0.0.1:5000
```

### Measured numbers

The full tables are in `docs/metrics.md`.

| What | Value |
|------|-------|
| Train stage time | 23.6 to 26.7 s (4 runs); 10.3 s with the squared loss |
| Whole pipeline, one `dvc repro` | ingest 10 s, validate 35 s, features 14 s, train 26 s |
| LightGBM fit per horizon | about 11 s |
| Saved model | 3.0 MB |
| Metrics per MLflow run | 88 |
| Tests | 117 passed |

### Viva questions for Stage 7

**1. Why do you purge training rows, and what would go wrong without it?**
The 24 h target of a training row at time t is the PM2.5 at t + 24 h. If t is within 24 hours of the start of the evaluation window, that target lies inside the window. The model would then train on values it is later scored on, and the error would look better than it is. So a row only trains if its target hour is before the window starts.

**2. How do you know a result can be reproduced?**
Each run is tagged with the full git commit hash, a flag that says whether tracked files had uncommitted changes, the DVC hash of the raw data and a hash of the feature values. The environment is pinned in `python_env.yaml` and matches `uv.lock`. Training is deterministic: I found that without two LightGBM settings, three identical runs differed by up to 5 µg/m³, so I turned them on and tested it. Running through `mlflow run` gave the same numbers as the pipeline.

**3. Your 24-hour model is slightly worse than Ridge. Why call LightGBM the main model?**
It is the model the design chose, and it is better at 1 h (7% below the best baseline) and on average (mean MAE 9.45 against 9.57 for Ridge). At 24 h the gap is 2.2% on 336 rows, which is within what a change of settings does. I report this openly, and the promotion rule decides what is served. If it keeps losing to Ridge in later retrains, the rule will block it.

**4. How does Ridge handle missing values, and why not just drop PM10?**
Ridge is a pipeline with a median imputer that also adds a flag column for every input that had gaps. The imputer is learned from training rows only and is part of the model object, so scoring treats gaps the same way. I kept PM10 even though 40% of it is missing because the input list is fixed in the LLD, and because the flag lets the model use the fact that PM10 is missing. LightGBM handles nulls itself.

**5. What does your MLflow run record that autolog would not?**
Autolog records parameters and a generic metric set. I log the git commit and a dirty flag, the DVC data version, a hash of the feature values, errors for every model, horizon and city, the ratio to the best baseline, error on high-pollution hours, the drift baseline used for monitoring, feature importance and residual plots, the exact package versions, and drift scores when a drift alert caused the retrain.

---

## Part 6: your three decisions

I applied all three, with one result you should know about (decision 3). Everything is committed. At the end `ruff check` passed, `pytest` gave 117 passed and 0 failed, and `dvc status` said up to date. I did not start Stage 8.

### 1. Drift: the decision rule

The design now follows my proposal, and it is in `docs/HLD.md`, the endpoint and metrics in `docs/LLD.md`, and the alert rules.

Drift is declared when both of these are true in the same 168-hour window:

- at least 3 cities have a PSI above their own threshold, and
- the pooled rolling 72 h MAE ratio is above 1.5.

The threshold of a city is the 95th percentile of its PSI in normal weeks. I get those by comparing each week (blocks 1 to 13) of each reference year with the same block of the other years. Kolkata has only two reference years, so it has no threshold and does not vote. That leaves 6 cities to vote.

The backend evaluates the rule and exports a single gauge, `aq_drift_detected`. The Prometheus alert `PM25DriftHigh` that starts a retrain is just `aq_drift_detected == 1`, so the rule lives in one place. I changed `ForecastErrorHigh` to a warning with no retrain, because a retrain now needs drift as well. The values 3 and 1.5 are settings, `DRIFT_MIN_CITIES` and `DRIFT_MAE_RATIO`. The LLD has the new `/ops/drift` response, three new metrics, and the new file `reports/drift_thresholds.json`.

**Not built yet:** the threshold file and the rule itself. They belong to Stage 11. The requirement you set is written into `docs/PLAN.md` as the acceptance test: the lockdown replay triggers it at least once, and normal weeks of earlier years do not. I will test both at Stage 11 by replaying the same weeks of 2016-2019 (counting false alarms) and then the lockdown.

I should be honest that this is not guaranteed to work. The weak spot I can already see is Hyderabad, where lockdown weeks do not stand out from normal weeks. With 6 voters and a limit of 3, the other cities may be enough, but I have not checked. If the rule cannot meet both conditions with these settings, I will report that and propose a change. I will not loosen the settings quietly until the demo fires.

### 2. Half-life changed to 90 days

I changed `train.half_life_days` to 90 and reran the pipeline on a clean tree. The effective number of training rows went from 14,542 to 43,518, and the results improved.

| Model | 1 h | 24 h |
|-------|----:|-----:|
| Persistence | 5.13 | 14.70 |
| Seasonal naive | 15.49 | 14.70 |
| Ridge | 5.03 | 14.25 |
| LightGBM | 4.50 | 13.54 |

LightGBM is the best model at both horizons now. It is 11% below the best baseline at 1 h and 5% below at 24 h. The evaluation window is still small (497 and 336 rows), so I read small gaps with care. It is still weaker than a baseline in Kolkata and Lucknow at both horizons, and in Chennai at 24 h. `docs/metrics.md` has the comparison with the 30-day run.

### 3. Promotion: best model per horizon

I recorded the rule in the HLD: for each horizon I register the better of Ridge and LightGBM by MAE, that model must be within 1.02 times the best baseline, and the limit is not relaxed. A new candidate is promoted only if its mean MAE over both horizons beats the champion's on the same window.

**What changed with decision 2:** your reasoning was that Ridge is best at 24 h (13.83 against 14.70 for persistence). That was true for the 30-day run. With 90 days, LightGBM is best at 24 h (13.54), and its ratio to the best baseline is 0.950. So with the current settings, LightGBM is registered at both horizons and the 1.02 rule is passed with room to spare. The rule is still useful, because a retrain on lockdown data may change which model wins.

**A gap I found:** `src/pipeline/aq_model.py` can only hold LightGBM models. If Ridge wins a horizon, the package has to hold the sklearn pipeline too. I did not build this, because I stopped this stage after these changes. I wrote it into the HLD and the plan for Stage 8.

**An assumption to confirm:** I read "best model" as the better of Ridge and LightGBM. I did not count persistence or seasonal naive as candidates, because a rule-based model has nothing to train or register. They are the yardstick for the 1.02 rule. Tell me if you meant something else.

### The L1 loss

The HLD already says it, and I checked it again. LightGBM uses the median (L1) loss, because models are compared by MAE. I first used the squared loss. On a 28-day test window L1 was better or equal in all 8 comparisons, by about 0.7 µg/m³ at 24 h. It takes about 11 s per horizon instead of 3 s.

### Other changes

The older parts of this file describe the 30-day run and the first drift threshold. I left them as a record of what I did at the time. Part 5's open decisions 1 to 3 are now closed by this part.

### Next: Stage 8

Stage 8 builds the `evaluate`, `test` and `register` stages, the registry with the `champion` and `previous` aliases, the promotion rule, and `scripts/rollback.py`. It completes the 7-stage DVC chain. I will start with these points, and I would like your answer on the first.

1. Confirm that "best model per horizon" means the better of Ridge and LightGBM.
2. Make the package able to hold a Ridge pipeline for a horizon (needed if Ridge ever wins). I would store it with `skops` or `joblib` as a model artifact and load it in `load_context`.
3. Build `evaluate`: score the candidate and the current champion on the same window, and write `reports/eval.json`.
4. Build `test` and `register` with the rule above, and rollback by moving the `champion` alias.
5. Run it on the first model, where there is no champion yet, and on a second run to show that a candidate that is not better is rejected and logged.

---

## Part 7: Stage 8, evaluate, test, register and rollback

Stage 8 is done. The pipeline now has all seven DVC stages (`dvc dag` shows ingest, validate, features, train, evaluate, test, register). `ruff check` passes, `pytest` gives 144 passed and 0 failed (it was 117), and `dvc status` says up to date. I did not start Stage 9. Your two answers are applied: "best model" is the better of Ridge and LightGBM per horizon, and the package holds either one.

### What I built

**The package holds Ridge or LightGBM per horizon.** The train stage now picks, for each horizon, whichever of Ridge and LightGBM has the lower MAE on the evaluation window (a tie goes to LightGBM). A LightGBM booster is saved as `h<N>.txt` and a Ridge pipeline as `h<N>.joblib`. `meta.json` has a `kinds` entry per horizon, and `aq_model.py` loads each file the way its kind needs. A package from before this change has no `kinds` and is read as all LightGBM. I used joblib because it comes with scikit-learn, so there is no new package. The cost is that a joblib file is a pickle: I load it only from my own registry. On the real data LightGBM wins both horizons, so the Ridge path is covered by unit tests but has not served a real forecast.

**`src/pipeline/registry.py`.** A `ModelRegistryClient` with the two aliases. `promote` creates a new registry version and moves `champion` to it and `previous` to the old champion. `rollback` does the same move to `previous`, or to a version I name, and it can itself be rolled back. Unknown version, no previous version and "already champion" raise a `RegistryError`, and nothing changes.

**The three stages.**

| Stage | What it does |
|-------|--------------|
| `evaluate` | Loads the candidate and the champion as MLflow packages and scores both on the same rows (the last 3 days before the cutoff). Writes `reports/eval.json`. With no champion it scores the candidate alone. |
| `test` | Applies the rule: each served model within 1.02 times the best baseline, and if there is a champion, a strictly lower mean MAE. Writes `reports/gate.json`. |
| `register` | If the gate passed, creates the registry version with tags (cutoff, git commit, data version, MAE per horizon, model kind per horizon) and moves the aliases. If not, registers nothing and tags the MLflow run `promotion=rejected` with the reasons. Writes `reports/register.json`. |

A rejection is not a failure. The `test` stage succeeds with `passed: false`, so the console can show it as a normal outcome and the run is not marked red. The module is called `test_gate.py` and not `test.py` so that pytest does not try to collect it.

**`scripts/rollback.py`.** `python -m scripts.rollback` moves `champion` back to `previous`. `--version N` names a version and `--list` shows the versions and aliases. Stage 10 will call the same code from `POST /ops/rollback`.

I updated `dvc.yaml`, `params.yaml` (a new `promotion` section with the registry name and the 1.02 limit), the HLD, the LLD (file formats and stage contracts), `docs/PLAN.md` and `docs/metrics.md`.

### How to run it

```
source .venv/bin/activate
dvc repro                       # runs whatever is out of date, through register
python -m scripts.rollback --list
python -m scripts.rollback      # champion <- previous
```

To train and judge a candidate again without redoing Spark, use `dvc repro -s -f train && dvc repro`.

### What I ran and what I measured

**First model.** There was no champion, so `evaluate` scored the candidate alone. Gate: passed, with ratios of 0.894 at 1 h and 0.950 at 24 h against the best baseline (Ridge in both cases). `register` created version 1 and set `champion`. The limit of 1.02 was applied as it is, not relaxed.

**Second run, a candidate that is not better.** I retrained on the same data and settings. Training is deterministic, so the candidate is the same model: mean MAE 9.018 for both. The gate rejected it with "mean MAE 9.018 is not lower than champion v1 9.018 on the same window". Nothing was registered, the champion is still version 1, and the run carries `promotion=rejected` and the reason. I chose this test because it shows the strictness of the rule: a tie is not promoted. It does not show a candidate that is clearly worse; the unit tests cover that case, with a worse mean MAE and with a baseline ratio above 1.02.

**Rollback drill.** To have two versions I registered the rejected run as version 2, then ran the script.

| Step | Result |
|------|--------|
| `python -m scripts.rollback` | champion 2 to 1, version 2 becomes `previous` |
| `python -m scripts.rollback` | champion 1 to 2 (the rollback undone) |
| `python -m scripts.rollback --version 1` | champion 2 to 1 |

After the drill I deleted version 2 and the `previous` alias, so the registry holds only version 1 as champion, and I checked that it loads by alias.

Stage times are in `docs/metrics.md`: `evaluate` 0.7 s, `test` under 0.1 s, `register` about 0.5 s. Scoring through the package matches the train stage within rounding.

### What went wrong

**The first registration failed.** `register` stopped with "Registered Model with name=aq-pm25 not found". MLflow does not create the registry entry when you create a version. The test I wrote first created the entry by hand, so it passed. The end-to-end test I added next did not, and it caught the problem. `promote` now creates the entry if it is missing.

**DVC said the model had changed, after nothing had.** After the first full run, `dvc status` showed `models/candidate` as modified. Loading the package imports its code, and Python wrote a `__pycache__` folder inside the tracked model folder. I now switch off bytecode writing in the evaluate stage, and the status stays clean. I would not have found this without running the real chain twice.

### Limits you should know about

- **The champion lives outside DVC.** The registry is in `mlflow.db`, which DVC does not track. `evaluate` depends on the champion, but DVC cannot see it change. This is fine in the normal flow, because only `register` changes it, but a rollback done by hand does not make DVC re-run `evaluate`. The retrain in Stage 11 always runs from `train` onwards, so it is not affected.
- **The window is short.** The comparison with the champion rests on 497 and 336 rows. A real improvement of a few percent is within the noise of that window, so the strict rule will sometimes reject a candidate that is slightly better and sometimes accept one that is slightly worse. I report it and did not tune it.
- **The champion was trained before the window it is scored on in a retrain.** When Stage 11 retrains at a later cutoff, the new window is newer than the champion's training data. That is intended: the question is which model handles the latest hours better.

### Viva questions I prepared

**1. Why compare the candidate and the champion on the same window?** If each model were judged on its own window, a model could win only because its window was easier. Scoring both on the same rows is the only fair test.

**2. Why is a tie rejected?** Promoting means the served model changes. A change with no measured gain has a cost (a restart, a new thing to explain) and no benefit.

**3. Why not register the rejected candidate?** The registry should list only models that were served or could be rolled back to. The rejected run is still in MLflow with its reason, so nothing is lost.

**4. How does a rollback work, and why is it safe?** It moves two aliases in the registry. No model files are touched, so it is instant, and the old champion becomes `previous`, so the rollback can be undone.

**5. Why not use Ridge when it ties LightGBM?** LightGBM is the main model in the design, and a tie gives no reason to switch.

### Next: Stage 9

Stage 9 serves the `champion` alias with `mlflow models serve` in a container and measures `/invocations` latency. I have no open question that blocks it.

## Part 8: Stage 9, the model server

### What I built

The model server is one container that serves the registered model through the MLflow API. It has three parts, all in `src/model_server/`.

**`mlflow models serve`.** This is the part the course asks for. It loads the package of the `champion` version and answers `POST /invocations` and `GET /ping`. I use one worker and `--env-manager local`, which means it runs in the container's own Python environment instead of building a new one. The container pins the same package versions as `python_env.yaml`.

**`proxy.py`, a small proxy on port 5001.** `mlflow models serve` cannot export Prometheus metrics, and the plan says every component must. So the public port belongs to my proxy. It forwards each request to MLflow, times `/invocations`, counts the rows per horizon, and serves `aq_model_predictions_total`, `aq_model_predict_duration_seconds` and `aq_model_loaded_version` on port 8001. If MLflow is down it answers 503, which the backend already treats as "model unavailable" (LLD section 1). Errors from MLflow, such as a bad horizon, pass through with their own status.

**`supervisor.py`, the watcher.** Every 30 seconds it reads the `champion` alias. If it moved, it downloads that version, starts a second MLflow process on the spare internal port (5002 or 5003), waits for `/ping`, switches the proxy to it, and stops the old process. A promotion and a rollback look the same to it, because both just move the alias. If the new model does not start, the old one keeps serving.

`docker/model_server/Dockerfile` builds the image from `python:3.12-slim`. It needs `libgomp1` for LightGBM, copies only the code it needs, and runs as a non-root user. `.dockerignore` keeps the data, the MLflow files and the virtual environment out of the build context.

I updated the LLD (the server layout, two ports, the new environment variables), the HLD (reload and proxy), the architecture text, `docs/PLAN.md` and `docs/metrics.md`.

### How to run it

Locally, from the repo with the virtual environment active:

```
MLFLOW_TRACKING_URI=sqlite:///mlflow.db python -m src.model_server.serve
curl localhost:5001/ping
curl localhost:5001/invocations -H 'Content-Type: application/json' -d @models/candidate/serving_input_example.json
curl localhost:8001/metrics | grep aq_model
```

In Docker (the registry is still a file on the host, so I mount the project at the same path; Stage 13 replaces this with an MLflow service):

```
docker build -f docker/model_server/Dockerfile -t aq-model-server .
docker run -d --name aq-model-server --memory 1g --user $(id -u):$(id -g) \
  -v "$PWD:$PWD" -e MLFLOW_TRACKING_URI="sqlite:///$PWD/mlflow.db" \
  -p 15001:5001 -p 18001:8001 aq-model-server
```

I mapped to ports 15001 and 18001 because the `a4-alertmanager` container posts to port 5001 on this machine, and I did not want it to hit my proxy.

### What I ran and what I measured

A sample call with the saved example row returned `{"predictions": [{"pm25": 119.9, "model_version": "1"}]}`. The container reported `healthy`. Serial latency through the proxy in the container: 1 row p50 4.9 ms, p95 8.1 ms; 14 rows (what the backend will send) p50 6.5 ms, p95 9.9 ms. The container used 504 MiB. The full table is in `docs/metrics.md`.

**Hot swap drill.** With the server running locally and polling every 5 seconds, I registered a second version, which moved `champion` to it, while a client sent a request every 50 ms for 25 seconds. The client saw both versions, `1` then `3`, and 0 failed requests. Then I rolled back, and 12 seconds later the server answered with version 1 again. I deleted the extra version and the `previous` alias afterwards, so the registry is back to version 1 as champion. (The extra version is numbered 3, not 2, because the Stage 8 drill version used the number 2 earlier.) I ran this drill outside Docker, not inside the container.

Tests: 12 new tests in `tests/test_model_server.py` for the proxy (forwarding, counting, error pass-through, 503 cases) and the watcher (first load, swap, rollback, failed load keeps the old model). The full suite is 156 passed, 0 failed, and `ruff` is clean.

### What went wrong

**My cleanup command killed my own shell.** I used `pkill -f` with a pattern that also matched the command line running it. I now find the process IDs with `ps` and kill them. Nothing was damaged, and I checked the registry afterwards.

**The first Docker build took several minutes.** Installing the full MLflow package on ARM is slow. Later builds reuse the cached layer.

### Limits you should know about

- **The container reads the registry through a bind mount.** MLflow stores absolute paths to the model files, so the host path has to exist inside the container. This works for the demo, and it is not a clean design. In Stage 13 the registry should be served by an MLflow service, and the old versions' paths need checking when I do it.
- **Memory doubles briefly during a swap.** Two models are loaded for a few seconds. I measured 504 MiB with one, not the peak with two.
- **One architecture only.** I built and ran the image on ARM64 only. Multi-arch comes in Stage 13.
- **The hot swap was not tested inside the container.** The same code ran there for the first load only.

### Viva questions I prepared

**1. Why a proxy in front of `mlflow models serve`?** MLflow gives no Prometheus metrics. The proxy is the smallest place to count predictions and time them without changing the model package.

**2. Why start the new model before stopping the old one?** A restart would drop requests during the load. Starting beside the old process and switching after `/ping` succeeds means no request fails, and a broken new model never replaces a working one.

**3. How does a rollback reach the server?** `scripts.rollback` moves the `champion` alias. The watcher sees a different version at its next poll and swaps to it, within 30 seconds.

**4. Why does every response carry `model_version`?** The version is set as an environment variable when the process starts, so a forecast can always be traced to the registry version, and from there to the run, the git commit and the data version.

**5. Why `--env-manager local`?** The container already has the pinned packages. Building a separate environment for each version would be slow and need network access.

### Next: Stage 10

Stage 10 builds the FastAPI backend from `docs/LLD.md`. It will call this server through `MODEL_SERVER_URL`. I have no open question that blocks it.

## Part 9: Stage 10, the FastAPI backend

### What I built

The backend is the only service the frontend will talk to. It lives in `src/backend/` and follows `docs/LLD.md` route by route. I split it into small classes so each one can be tested alone.

| File | What it does |
|------|--------------|
| `app.py` | `create_app(settings, ...)` builds the app and all routes. Collaborators are arguments, so tests pass fakes. |
| `forecaster.py` | `Forecaster`: finds the city's feature row for the current replay hour, asks the model server for both horizons in one call, clips and rounds, adds the AQI category. |
| `replay.py` | `ReplayClock`: the simulated "now". It has no thread. It stores where the replay was when it last changed and computes the current hour from the wall clock when asked. |
| `store.py` | Reads `data/features/serving.parquet` once (30,576 rows) and looks up a (city, hour). |
| `model_client.py` | Calls `/invocations` and `/ping`. Any failure becomes one error type, which the API turns into 503 `MODEL_UNAVAILABLE`. |
| `registry_view.py` | The registry with a 30 s cache. If the registry is down, it returns what it knew before, and forecasts still work (their run id and commit become `null`). |
| `pipeline_view.py` | Reads `reports/runs.jsonl` for `/pipeline/stages` and `/pipeline/runs`. |
| `ops.py` | `RetrainQueue`: writes `ops/requests/<id>.json`, refuses a second one while one is active, and applies the 30-minute cooldown to alerts. |
| `drift.py` | Builds the `/ops/drift` body. See the limits below. |
| `metrics.py` | The backend metrics from LLD section 5. |
| `errors.py` | One error body for every non-2xx answer, including FastAPI's own 422, 404 and 405. |

The endpoints are `/health`, `/cities`, `/aqi/categories`, `/forecast`, `/pipeline/stages`, `/pipeline/runs`, `/pipeline/models`, `/metrics`, and the ops endpoints `/ops/drift`, `/ops/replay` (GET and POST), `/ops/retrain`, `/ops/rollback` and `/ops/alerts`. The ops endpoints need `Authorization: Bearer <OPS_API_KEY>`. I compare the key with `hmac.compare_digest`, and the backend refuses to start without a key.

**Input checking.** `city` is checked against the list of seven cities (404 for anything else, 422 if missing). The request bodies are Pydantic models with ranges (`speed_hps` 0.1-20, `reason` 1-200 characters, `limit` 1-100). Malformed JSON gives a 422. A crash inside an endpoint is caught by a middleware, logged with its traceback and returned as a generic 500 with no internals.

**Metrics.** A middleware counts and times every request. The path label is the route template, and a path that matches no route is labelled `unmatched`. I did this so a scanner hitting random URLs cannot create unlimited label values.

I changed `ModelRegistryClient.versions()` to also return the creation time, because `/pipeline/models` shows it. Nothing else in the pipeline changed.

### How to run it

```
export PATH=$PWD/.venv/bin:$PATH
MLFLOW_TRACKING_URI=sqlite:///mlflow.db python -m src.model_server.serve &   # ports 5001, 8001
OPS_API_KEY=anything MODEL_SERVER_URL=http://localhost:5001 \
  MLFLOW_TRACKING_URI=sqlite:///mlflow.db OPS_DIR=/tmp/ops python -m src.backend.main
curl localhost:8000/health
curl 'localhost:8000/forecast?city=Delhi'
curl -H 'Authorization: Bearer anything' -X POST localhost:8000/ops/replay \
  -H 'content-type: application/json' -d '{"action":"start","speed_hps":20}'
```

There is no certificate yet, so the backend serves plain HTTP and says so in the log. HTTPS comes in Stage 15. The tests run without any server: `pytest tests/test_backend.py`.

### What I ran and measured

I ran the backend against the real model server with champion v1. The forecast for Delhi at the replay start returned 28.2 µg/m³ at 1 h (Good) and 51.4 at 24 h (Satisfactory), with run id `0b70053677db...` and commit `748c0f8` from the registry. `/ops/drift` without a key returned 401. After `start` at 20 hours per second, the clock read 2020-03-27 12:00 three seconds later. `/forecast` took 8.7 ms at p50 and 15.6 ms at p95 over 200 serial calls (table in `docs/metrics.md`). The new tests are 92, and the whole suite is 248 passed, 0 failed. `ruff` is clean.

### What went wrong

**`pkill -f` killed my shell again.** I repeated the Stage 9 mistake while restarting the model server, and the command ended with exit code 144. I now list processes with `ps`, pick the PIDs and kill those. Nothing was damaged.

**I started the model server without the virtual environment on `PATH`.** `mlflow models serve` calls `uvicorn` by name and failed with code 127. Putting `.venv/bin` on `PATH` fixed it.

**My first version called a run "running".** `runs.jsonl` cannot tell me that a run is in progress, and DVC skips unchanged stages, so a run with only two lines is normal. A run with no failed stage is now `success`. I also stopped attaching `register.json` to a run that did not run the register stage, because it would show another run's promotion result.

**One test I left half-written.** I had a placeholder test for `NO_DATA`. I replaced it with a real one that starts the clock outside the stored period.

### Limits you should know about

- **`/ops/drift` returns the shape, not the scores.** All PSI and MAE numbers are `null` and `any_drift` is always false. The drift computation, the thresholds file and the acceptance test belong to Stage 11 in the plan, and I did not want to build half of it here. The LLD says so. Until Stage 11, `aq_drift_detected` stays at 0.
- **`/pipeline/runs` knows `promoted` only for the newest run.** The file stores no promotion result per run. Older runs show `null`.
- **The replay clock lives in memory.** If the backend restarts, the replay goes back to the start and stops.
- **A forecast needs a feature row for the exact replay hour.** If the data has a gap, the answer is 503 `NO_DATA`, as in the LLD.
- **The retrain request is only a file.** Nothing consumes it until the ops runner exists (Stage 11). I tested the file and the cooldown, not a real retrain.
- **No Dockerfile yet.** It comes with Stage 13. I did not measure the backend's memory.
- **No TLS yet** (Stage 15).

### Viva questions I prepared

**1. Why does the replay clock have no thread?** A thread needs starting, stopping and locking, and a test would have to wait for real time. The clock only stores its state and computes the hour when asked, so a test passes a fake timer and checks exact values.

**2. Why does the backend send the model both horizons in one call?** One request costs less than two, and both answers come from the same model version. The backend checks that the two predictions report the same version, and answers 503 if they do not.

**3. Why does the backend not run `dvc repro` itself?** Training needs Spark and 2 GB of memory, and the backend container has a small limit. It writes a request file and a separate runner on the host does the work. That also means the backend never needs Docker access.

**4. What happens if the registry is down?** Forecasts still work. The model version comes from the model server's own answer, and the run id and commit become `null`. `/pipeline/models` returns the last list it knew.

**5. Why does every error have the same JSON shape?** The frontend can show one friendly message from `error.code` and never has to guess the format. I overrode FastAPI's default 422, 404 and 405 bodies for this reason.

**6. Why is the API key compared with `compare_digest`?** A normal string comparison stops at the first different character, so its timing can leak how much of a guess was right.

### Next: Stage 11

Stage 11 builds the drift module and the replay script, the ops runner that turns a request file into `dvc repro`, and the acceptance test: the lockdown replay must trigger drift at least once, and normal weeks of earlier years must not. It also fills in `/ops/drift`. I have no open question that blocks it.

---

## Part 10: Stage 11, drift detection and automated retraining

Stage 11 is done. The acceptance test passes, but not with the rule I designed. The first rule failed both conditions, so I measured why, and we changed it together before I built anything around it. At the end `ruff check` passed, `pytest` gave 293 passed and 0 failed, `dvc status` said up to date, and `python -m scripts.replay` exited with 0.

### The rule changed, and why

The HLD rule was: at least 3 cities above their own PSI threshold **and** a pooled 72 h MAE ratio above 1.5. Before writing the module, I scored every hour of the replay window in 2016-2019 and in 2020 with that rule. It fired for 13 hours in normal 2018, and it never fired during the lockdown.

PSI was not the problem. The lockdown pushes up to 5 cities above their thresholds at once. The MAE condition was the problem. The model's error grows with the PM2.5 level, and lockdown PM2.5 is about half of a normal spring. So champion v1 made *smaller* errors during the lockdown than in any earlier year, in all 7 cities, and the ratio never got above 1.47. Earlier springs, with their higher levels, had ratios above 1.5 for hundreds of hours. The idea "PSI says the inputs changed, the MAE says it hurts" was wrong for this model: the lockdown changed the inputs a lot but did not hurt the 1 h forecast.

The two fallbacks in my plan (2 cities instead of 3, then removing Hyderabad) both loosen only the PSI side. With either one, the lockdown still got 0 hours, because the MAE condition blocked it, and 2 cities made the false alarms worse. So I stopped and rethought the rule. I chose a PSI-only rule, with the number of cities set from normal weeks only. In 2016-2019 at most 3 cities were ever above threshold at the same hour, so the rule needs 4 of the 6 voting cities. The MAE ratio is still computed and exported, and it drives the `ForecastErrorHigh` warning, but it no longer starts a retrain. HLD, LLD and PLAN say this in the same words.

### What I built

| File | What it does |
|------|--------------|
| `src/monitoring/drift.py` | PSI, reference bins, leave-one-year-out thresholds and `DriftDetector`, which applies the rule for one hour. The features stage, the backend and the replay script all use this one module, so they cannot disagree. |
| `src/pipeline/features.py` | Now also writes `reports/drift_thresholds.json`. Spark selects the reference values (about 60,000 numbers); the PSI is computed in Python with the module above. `reference_frame` is shared with the baseline code, so both use the same hours. |
| `src/backend/drift.py` | `DriftReport` fills `/ops/drift` and the drift gauges with real numbers. PSI needs only the stored features, so drift is detected even when the model server is down. The MAE ratio asks the model server for the last 72 hours of 1 h forecasts in one call, divides by the champion's `mae_1h` tag, and is cached per replay hour and champion version. |
| `src/backend/ops.py`, `app.py` | A drift alert now saves `trigger` and a `drift` snapshot in the request file. |
| `src/ops/runner.py` | `OpsRunner`: takes the oldest queued request, checks free memory (2,500 MB), moves `cutoff` in `params.yaml` to the request's simulated time, writes `reports/drift_trigger.json`, runs `dvc repro` with `PIPELINE_TRIGGER` and `PIPELINE_RUN_ID`, reads `register.json`, and after a promotion runs the smoke check. If the new version does not answer within 180 s, it rolls back to `previous`. |
| `scripts/replay.py` | The acceptance test. It replays 25 March to 30 June hour by hour for 2016-2019 (each year against a reference built without it) and for 2020 (against the saved reference), and writes `reports/drift_replay.json`. |
| `monitoring/alerts.yml`, `prometheus.yml`, `alertmanager.yml` | The two drift alert rules and the webhook to `/ops/alerts` with the bearer key from a gitignored file. Only the backend is scraped so far. Stage 14 adds the rest. |

New settings in `params.yaml`: `features.threshold_percentile` (95), `threshold_blocks` ([1, 13]), `threshold_min_years` (3), `drift.min_cities` (4) and `drift.mae_ratio_warn` (1.5).

### How to run it

```
export PATH=$PWD/.venv/bin:$PATH MLFLOW_TRACKING_URI=sqlite:///mlflow.db
python -m scripts.replay --with-mae          # acceptance test, about 4 s

# end to end (frontend and Grafana must not run)
echo "$OPS_API_KEY" > monitoring/secrets/ops_api_key
python -m src.model_server.serve &
OPS_API_KEY=... MODEL_SERVER_URL=http://localhost:5001 OPS_DIR=$PWD/ops python -m src.backend.main &
MODEL_SERVER_URL=http://localhost:5001 OPS_DIR=$PWD/ops python -m src.ops.runner &
docker network create aq-s11
docker run -d --name aq-s11-alertmanager --network aq-s11 --network-alias alertmanager \
  --add-host backend:host-gateway -p 19093:9093 \
  -v $PWD/monitoring/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro \
  -v $PWD/monitoring/secrets:/etc/alertmanager/secrets:ro prom/alertmanager:v0.28.1
docker run -d --name aq-s11-prometheus --network aq-s11 --add-host backend:host-gateway \
  -p 19090:9090 -v $PWD/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro \
  -v $PWD/monitoring/alerts.yml:/etc/prometheus/alerts.yml:ro prom/prometheus:v3.5.0 \
  --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.retention.time=2d
curl -H "Authorization: Bearer $OPS_API_KEY" -H 'content-type: application/json' \
  -X POST localhost:8000/ops/replay -d '{"action":"start","speed_hps":0.5}'
```

I used ports 19090 and 19093 because 9090 and 9093 belong to another project's containers on this VM, which I did not touch. In Stage 13 these become compose services.

### What I ran and what I measured

All numbers are in `docs/metrics.md`, Stage 11. In short:

- **Acceptance test: passed.** The lockdown triggers drift for 661 of 2,185 scored hours in 5 episodes, first at 2020-03-31 23:00, the first hour with a full window. Normal weeks of 2016-2019 trigger it for 0 hours.
- **End to end:** I started the replay at 17:13:09. The rule became true at sim time 2020-03-31 23:00 (about 17:18:43). `PM25DriftHigh` fired at 17:20:09, the webhook wrote the request at 17:20:13, and the runner started `dvc repro` at 17:20:22 with the cutoff moved to 2020-04-02 19:00. At 17:21:30 the gate passed, v4 was registered as champion, the model server swapped to it, and the smoke check passed. From drift to new model was about 2 min 47 s.
- **The gate:** on the lockdown evaluation window the candidate's mean MAE was 6.467 against 6.750 for v1, and 0.881 and 0.890 times the best baseline. The MLflow run is tagged `trigger=drift_alert` and has the `drift_*` metrics.
- **Memory:** the whole VM peaked at 5,008 MB used, and never had less than 2,389 MB available, during the retrain with model server, backend, Prometheus and Alertmanager running.

### What went wrong

**The designed rule could not pass.** That is the main story of this stage (above). I am glad I measured before building, because otherwise I would have built the whole loop around a trigger that never fires.

**My first scratch study understated the MAE ratio in normal years.** It reported a median of 1.16 for 2017, while `scripts/replay.py` later gave 2.53. I checked against the per-city error table, and the script is right: 2017 had 1 h errors of 5 to 21 µg/m³ against a denominator of 4.50. The bug was in the scratch script, which I did not keep. The lockdown numbers matched in both (max 1.47), so the decision did not change. The numbers in the docs come from the committed script, not the scratch study. The first numbers I looked at before I chose the rule came from the scratch study (for example "MAE > 1.5 in 2018: 52 h"; the correct figure is 1,949 h).

**A test failed because of my test data.** In the replay test I shifted 2019 and expected 2017 to stay quiet. But 2017's leave-one-out reference contains 2019, so 2017 rightly looked drifted. I split it into a clean case and a shifted case.

**Ruff found 31 problems** in my first version: long lines and docstrings not in the imperative. I fixed them and formatted only the files I had changed.

**The architecture document promised things the runner does not do:** pausing the frontend and Grafana, and committing `dvc.lock`. Pausing needs the compose stack, so for now the runner refuses to start below 2,500 MB of free memory. I decided against the automatic commit: it would also commit the cutoff change in `params.yaml`, and the MLflow run already records the commit, the cutoff and the pipeline run id. I corrected the document.

### Limits you should know about

- **The margin is zero.** The most cities above threshold at once in a normal week is 3, and the rule needs 4. One unusual normal week would be a false alarm. The thresholds and the city count were also chosen on the same 2016-2019 weeks I count false alarms on, so the false-alarm result is in-sample. I never used lockdown data to tune.
- **Hyderabad is above its threshold for only 1 hour of the lockdown**, so in practice the rule is 4 of 5 cities. 2016 has only 5 voters because Jaipur has no data that year.
- **The MAE ratios for 2016-2019 are in-sample**, because those years are in the training data. That makes the normal years look better than they are, and they still had ratios far above 1.5.
- **The alert keeps firing after a retrain.** The PSI reference stays the same-season history, so the lockdown still looks like drift to v4. The 30-minute cooldown is what limits retrains. At 0.5 h/s that is one retrain per 900 simulated hours. I stopped the replay after the first retrain.
- **Auto-rollback is tested with fakes only.** I did not make a real model fail its smoke check. The smoke check only checks that the new version answers with a finite value of 0 or more for one stored row (Delhi, 1 January 2020). It does not check accuracy.
- **The repository now holds the retrained state.** `params.yaml` has `cutoff: "2020-04-02 19:00:00"` and `dvc.lock` matches it. Champion v4 lives only in my local `mlflow.db`, which is not in git. The retrain run is tagged `git_dirty=true`, because the runner changed `params.yaml`. To repeat the demo from the start: `python -m scripts.rollback --version 1`, put the cutoff back to `2020-03-24 23:00:00`, run `dvc repro`, and delete `ops/requests/*`.
- **Prometheus and Alertmanager ran as plain containers** for this test. Compose, memory limits and the other alert rules come in Stages 13 and 14.

### Viva questions I prepared

**1. Why did you drop the MAE condition? Isn't a retrain without lower accuracy pointless?**
On this model the lockdown lowers the absolute error, because there is less PM2.5 to get wrong. So no error ratio above 1 could ever confirm it. The input shift is real and large, and a retrain on the new regime is still the right reaction. The promotion gate stops a retrain that does not help: v4 was promoted only because it beat v1 on the lockdown window (6.467 against 6.750).

**2. How did you pick 4 cities without looking at the lockdown?**
I counted, for every hour of 2016-2019, how many cities were above their threshold. The maximum was 3, so 4 is the smallest number that never fires on normal weeks. Only after fixing it did I score 2020.

**3. Why compute the PSI thresholds in the features stage?**
They depend only on the reference years, which the features stage already selects with Spark. Being a DVC output, they are versioned with the data and change only when the data or the settings change.

**4. What stops a retrain storm?**
Three things: the backend accepts no new request while one is queued or running, a 30-minute cooldown after each request, and Alertmanager's 30-minute repeat interval.

**5. What happens if the new model is broken?**
The runner waits up to 180 s for the model server to answer a test forecast with the new version and a sane value. If that does not happen, it moves `champion` back to `previous`, the watcher swaps the old model back in, and the request is marked `rolled_back`.

**6. Why does the retrain change `params.yaml`?**
The cutoff is the input that decides which hours the model trains on, and DVC tracks it as a parameter. Changing it is what makes `dvc repro` rebuild features and retrain. The MLflow run records the new cutoff, so the model can still be traced to its code and data.

### Next: Stage 12

Stage 12 is the Streamlit frontend: the forecast page for non-technical users and the pipeline console. The console will show the drift status from `/ops/drift` and the retrain requests. I have no open question that blocks it.

## Part 11: the episode gate, Stage 12 (frontend) and Stage 13 (Docker), written while you were away

This part covers three tasks done back to back. The first two are done and committed. The third is only partly done, and I say exactly where it stops below.

### 1. One retrain per drift episode (commit `474db67`)

**The problem.** After a retrain the PSI reference does not change, so the lockdown still looks like drift and the alert keeps firing. Only the 30-minute cooldown held it back, which in real time means a retrain every half hour.

**What I built.** `EpisodeGate` in `src/backend/ops.py`. A drift alert that creates a retrain request opens an episode. While it is open, further drift alerts are ignored. The episode closes when the drift rule has been false for `drift.episode_clear_hours` simulated hours in a row. The backend feeds the gate with the rule's value on every Prometheus scrape, every `/ops/drift` call and every alert. The state is in `ops/episode.json`, so a restart does not forget an open episode.

**Why 72 hours.** I took it from `reports/drift_replay.json`. The first four lockdown episodes are separated by gaps of 28, 49 and 37 hours, so 72 merges them into one. The fifth starts 250 hours after the fourth, so it counts as a second one. The cost is that a real second shift within 72 hours of a retrain is not retrained on until the rule has been quiet. Manual retrains do not open an episode.

**Tests.** `test_episode_gate_closes_after_quiet_period` (71 hours is not enough, a drift hour restarts the count, 72 closes it, state survives a restart) and `test_alerts_one_retrain_per_episode` (cooldown over, still ignored, then allowed after the quiet period). Settings: `drift.episode_clear_hours` in `params.yaml`. HLD and LLD are updated.

### 2. Stage 12: Streamlit frontend (commit `d843bba`)

| File | What it does |
|------|--------------|
| `src/frontend/client.py` | `BackendClient`, the only door to the backend. Reads `BACKEND_URL` (and `BACKEND_CA_FILE` for the self-signed certificate of Stage 15). Sends the API key only to the paths where the caller passes one. Turns every failure into a `BackendError` with a code. Times each call and counts failures. |
| `src/frontend/forecast_page.py` | City dropdown filled from `/cities`, one colour card per horizon, advice text, colour guide, Refresh button, plain sentences when the backend or the model is down. |
| `src/frontend/console_page.py` | Health and replay status, the DVC DAG drawn with Graphviz and coloured by each stage's last status, the stage table (duration, rows, rows/sec), successful and failed run counts with the run table (it has the error column), model versions, links to MLflow, Grafana and Prometheus. After the operator types the API key: drift status and the replay, retrain and rollback buttons. |
| `src/frontend/helpers.py` | Pure functions (text colour, time format, card HTML, DAG source) so they can be unit tested. |
| `src/frontend/metrics.py` | `aq_ui_page_views_total`, `aq_ui_backend_call_duration_seconds`, `aq_ui_backend_errors_total` on port 8502. |

**Decisions.** The console does not read `OPS_API_KEY` from the environment. If it did, anyone who could open the page could press retrain. The operator types the key, and the first `/ops/drift` call is the check: a wrong key shows an error and no buttons. A test caught my first version, which still showed the buttons after a wrong key. The LLD environment table is changed to say this. Card text is HTML-escaped, and a test checks that. The page layout is Streamlit's own column flow, which stacks on a narrow screen. I did not test it on a real phone.

**What I ran.** I started the real model server and backend and checked the client against them: `/pipeline/stages`, `/pipeline/runs`, `/pipeline/models` and `/ops/drift` return what the pages need, a wrong key gives `UNAUTHORIZED` (401), an unknown city gives `UNKNOWN_CITY`, and a dead port gives `UNREACHABLE`. Streamlit served `/console` with HTTP 200. The page tests use Streamlit's `AppTest` with a fake backend. Test count after this stage: 311 passed, ruff clean.

**Not done: the screenshots.** The only browser on this VM is Firefox as a snap, and headless mode hangs on it. I tried to install Playwright and its Chromium, but even the pip download of Playwright stalled and I stopped it (the VM's network is slow, the same reason the image builds below are slow). The screenshots of both pages for the user manual are still missing. To take them: run the stack (below) and use the browser on your desktop.

**Run it.**

```
export PATH=$PWD/.venv/bin:$PATH MLFLOW_TRACKING_URI=sqlite:///mlflow.db OPS_API_KEY=<key>
python -m src.model_server.serve &
python -m src.backend.main &
BACKEND_URL=http://localhost:8000 PYTHONPATH=. streamlit run src/frontend/app.py
```

### 3. Stage 13: Docker (partly done, committed with these notes)

**Written:** a Dockerfile for the frontend, backend and pipeline (the model server already had one), each with a pinned `requirements.txt`, non-root user, health check and only the source folders it needs. `docker-compose.yml` has the `serve` profile (frontend, backend, model-server, mlflow, prometheus, alertmanager, pushgateway, node-exporter, grafana) and the `batch` profile (pipeline), `mem_limit` on every service, and ports for Prometheus, Alertmanager, Grafana and MLflow that do not collide with the other project's containers (19090, 19093, 13000, 5000). `scripts/build_multiarch.sh` builds and pushes the amd64 and arm64 images.

**Checked:** `docker compose --profile serve --profile batch config` is valid.

**Not checked, and why:**
- **Image builds.** pip downloads on this VM are very slow (Streamlit and MLflow are large), so the builds took many minutes. Both finished afterwards: `aq-frontend` (825 MB) and `aq-backend` (1.33 GB) build on arm64. The pipeline image is not built. I have **not** started any container or run the stack in compose, so whether the images start, and the memory use of each container, are unmeasured.
- **Multi-arch push.** It needs `docker login` (your Docker Hub password) and QEMU emulation for amd64 on this arm64 VM, which I cannot set up without sudo. The script is written but untested. This is a blocker for you to decide.
- **Pushgateway and Grafana wiring.** The services exist, but Prometheus still scrapes only the backend and Grafana has no dashboards. That is Stage 14.

**Design points to defend.**
- *The same absolute path inside containers.* MLflow stores artifact locations as absolute host paths (`/home/.../mlruns/1/...`). The model server cannot find a model there unless the same path exists inside the container, so compose mounts `mlruns` and `mlflow.db` at `${HOST_PROJECT}`. It is ugly, and it is honest: the registry was created on the host. A clean fix is to log new runs with `--serve-artifacts` through the MLflow server, but that does not rescue the existing versions.
- *The MLflow service reuses the model-server image.* It already contains MLflow, and a fourth Python image would cost another gigabyte on a small disk.
- *`user: HOST_UID:HOST_GID`.* The backend writes request files into `./ops` and MLflow writes the SQLite file. The image has a non-root user (10001), but bind mounts owned by my user would be read-only to it. Running as the host user keeps it non-root and writable.
- *The pipeline image holds only the environment.* The project folder is mounted, so `dvc repro` works on the real repo and DVC cache.

### Viva questions I prepared

**1. Why does a retrain not simply restart whenever the cooldown ends?**
Because the cooldown measures real time, and drift is a property of the simulated data. During a 75-day lockdown the rule stays true for days. The episode gate links the end of the suppression to the rule itself, so one episode gives one retrain.

**2. How did you pick 72 hours?**
From the measured gaps between lockdown episodes: 28, 49 and 37 hours join together, 250 hours stays separate. The limit of that is that I chose it on this one replay.

**3. Why is the API key typed into the console and not set as an environment variable?**
A key in the frontend's environment means the frontend acts for every visitor. Typing it keeps the authority with the person, and the backend is still what decides, in constant time.

**4. Why does the frontend import nothing from the backend?**
So it can be rebuilt, moved or replaced knowing only `BACKEND_URL` and `docs/LLD.md`. Its image copies `src/frontend` and two small shared helpers, nothing else.

**5. Why does MLflow need the project mounted at the same path?**
Run artifact locations are stored as absolute paths when the run is logged. A container with a different path cannot open them.

**6. Why `mem_limit` on every service, and why two profiles?**
The VM has 8 GB. Spark's driver alone takes 2 GB. Running the batch and the full stack at once would push the machine into swap, so compose makes them separate profiles and the runner refuses to start with less than 2,500 MB free.

### What needs you

1. Docker Hub login and QEMU/binfmt for the multi-arch push (needs sudo or your password).
2. Screenshots of both pages (a browser on your desktop). The stack is running; the frontend is at http://localhost:8501.

## Part 12: running the serve stack in compose

The goal of this part was to build the pipeline image, bring up the serve stack, check it end to end, record memory, and leave it running.

**The stack runs.** `docker compose --profile serve up -d` started all nine services. The backend, model-server, frontend and mlflow report `healthy`. I used host ports 8000, 8501, 5000, 19090, 19093 and 13000, so nothing collides with the a4-* containers (3000, 9090, 9093, 9100), which I did not touch. I created a gitignored `.env` with the API key (copied from `monitoring/secrets/ops_api_key`) and `HOST_PROJECT`, `HOST_UID`, `HOST_GID`.

**End to end.** The backend answered `/forecast?city=Delhi` with model version 4 after calling the model server and reading the registry through the MLflow container. From inside the frontend container, `BackendClient` with `BACKEND_URL=http://backend:8000` got a Chennai forecast and the pipeline views. So frontend, backend, model server and registry talk to each other over the compose network. I did not click through the pages in a browser. That is what the screenshots are for.

**What went wrong: MLflow kept dying.** At `mem_limit: 512m` it was OOM-killed 11 times in 5 minutes, and at 1 GiB it still hit the limit. MLflow 3.17's server starts 4 workers and a background job runner. I set `--workers 1` and `MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false`; it now runs at about 350 MiB with 0 restarts, so I set 768m. Because MLflow was down for the first minutes, the backend and model server used up their retries and showed `unhealthy`. I restarted them. Two weaknesses remain: they have no wait-for-MLflow logic beyond `depends_on` (which only waits for the container to start), and a cold MLflow start takes a minute or more. I gave MLflow its own health check, because the image's built-in one checks port 5001.

**Memory.** The nine containers use about 1.24 GiB in total at idle (table in `docs/metrics.md`). The HLD planned about 3 GB, so the plan was cautious. Idle is the key word: no replay is running and Grafana has no dashboards.

**The pipeline image builds** (`aq-pipeline`, 2.57 GB, arm64). I only built it and checked that it imports pyspark 3.5.9, MLflow 3.17.1, DVC and LightGBM and has Java 21. I did not run it, because the batch and the serve stack must not run together. The first two build attempts failed or hung: the 318 MB pyspark download is slow on this VM and one attempt ended with a broken pipe. I added `--retries 10 --timeout 60` to the pip line in `docker/pipeline/Dockerfile`, and the third attempt finished. I also had two duplicate builds running at once for a while, which slowed both.

### Viva questions I prepared

**0. Why does the pipeline image hold only the environment?**
The project folder is mounted at its host path, so `dvc repro` works on the real repo, the DVC cache and `mlflow.db`. Baking the code in would give a second copy that could drift from git.

**1. Why did `depends_on` not stop the backend from failing at start?**
`depends_on` waits for the other container to start, not for the service inside it to answer. MLflow needed over a minute. A proper fix is `condition: service_healthy` on the dependency, which I have not added yet.

**2. How did you find the MLflow memory problem?**
`docker stats` showed it pinned at its limit, `docker inspect` showed 11 restarts and `OOMKilled`, and the logs showed worker processes dying. I then removed the two things that cost memory (extra workers, the job runner) instead of only raising the limit.

**3. Why is idle memory so far below the plan?**
The plan counted the limits, not use. At idle nothing is computing. Under a replay and a retrain the model server and backend grow, and Spark runs in the other profile.

**4. How do you know the containers are really talking to each other?**
The forecast comes from the model server (version 4 in the answer), the version metadata from the registry through MLflow, and the frontend client reached the backend by its compose name.

## Part 13: UI paths, the demo note, and a start order that needs no restarts

**"Page not found" on `/forecast`.** Streamlit always serves the default page at `/` and ignores its `url_path`. I had made Forecast the default, so `/forecast` did not exist. The fix in `src/frontend/app.py`: the default page is now a hidden redirect to Forecast, the navigation is hidden, and the sidebar links to the two real pages, `/forecast` and `/console`. The paths are written down in `docs/LLD.md`, section 9. A new test, `test_app_serves_forecast_and_console_paths`, loads the real `app.py` with `AppTest`, checks that the registered paths are exactly `""`, `forecast` and `console`, and opens each one. I could not open the page in a browser on this VM (no working headless browser), so the popup itself is checked only through Streamlit's page resolution, not by eye.

**Demo note.** The forecast page now says, under the intro: "This is a demo. It replays real measurements from March to June 2020 as if they were happening now, so the dates you see are from 2020." The replay window in `params.yaml` is 2020-03-25 to 2020-06-30. A test checks the note is there.

**Start order.** Plain `depends_on` only waits for a container to start, which is why the backend and model server gave up in Part 12. Now each service waits for the one before it to be healthy: mlflow → model-server → backend → frontend (`condition: service_healthy`). MLflow, the model server, the backend and the frontend have health checks in compose. During the start period the check runs every 5 s (`start_interval`), so compose notices a healthy service quickly instead of waiting a full 30 s interval. A full `down` and `up -d` brought all 9 containers up and healthy in about 36 s with 0 restarts, and a forecast worked at once (numbers in `docs/metrics.md`).

**Screenshots.** The two files in `docs/screenshots/` are early placeholders. They are not committed; you will retake them when the UI is final.

Tests: 313 passed, ruff clean.

## Part 14: Stage 14, Prometheus and Grafana

### What I built

| File | What it does |
|------|--------------|
| `monitoring/prometheus.yml` | 9 scrape jobs every 15 s: backend, model-server (`:8001`), frontend (`:8502`), mlflow, pushgateway (`honor_labels`), node-exporter, and Prometheus, Alertmanager and Grafana themselves. |
| `monitoring/alerts.yml` | 6 rules: `PM25DriftHigh` (the only one with `action=retrain`), `ForecastErrorHigh` (warning), `BackendErrorRateHigh` (5xx share above 5% for 2 min), `ModelServerErrors`, `TargetDown`, `PipelineStageFailed`. |
| `monitoring/alerts_test.yml` | promtool unit tests for four of the rules, on made-up series. |
| `monitoring/grafana/provisioning/` | The Prometheus data source and the dashboard folder, read by Grafana at start. |
| `monitoring/grafana/dashboards/aq_service.json` | Home dashboard: model versions, drift, replay clock, firing alerts, targets up; backend rate, latency and error rate; forecasts; model-server rate and latency; PSI per city with its threshold; MAE ratios; frontend views and call latency; memory and CPU. |
| `monitoring/grafana/dashboards/aq_pipeline.json` | Stage duration, rows per second and status from the Pushgateway, last success, last push, retrain requests, MLflow request rate and latency. |
| `docker/mlflow/Dockerfile` | The model-server image plus `prometheus-flask-exporter`, so `mlflow server --expose-prometheus` works. |
| `src/frontend/main.py` | Starts the frontend exporter, then Streamlit. |
| `scripts/push_stage_metrics.py` | Re-pushes the last stage records to the Pushgateway. |

Compose changes: Prometheus keeps its data in a named volume (2-day retention, so it survives a restart). The Pushgateway is in both profiles, saves to a file and has host port 19091 for the ops runner. Grafana gets the provisioning folders, an admin password from `.env` (`GRAFANA_ADMIN_PASSWORD`, which I generated) and read-only anonymous access, so the console's Grafana link opens without a login. The backend now also exports its own process memory and CPU.

Both dashboards refresh every 15 s, the same as the scrape interval. Faster would only redraw the same points.

### What went wrong

**The frontend showed as down.** The exporter was started inside `app.py`, and Streamlit runs that script only when someone opens a page. Right after a start, nobody had, so Prometheus got "connection refused" and `TargetDown` fired for the frontend (it did, at 10:13, and resolved when I fixed it). The fix is `src/frontend/main.py`: it starts the exporter in the same process and then hands over to Streamlit. The image now runs `python -m src.frontend.main`.

**MLflow had no metrics.** `--expose-prometheus` needs `prometheus-flask-exporter`, which the model-server image does not have. I added a one-line image on top of it instead of rebuilding the model-server image, because the full pip install on this VM takes many minutes. Its metrics are named `mlflow_http_request_*`, not `flask_http_request_*` as I first wrote in the dashboard, so the first MLflow panel was empty until I checked the real names.

**No pipeline numbers.** The batch has not run since the Pushgateway was wired, so the pipeline dashboard was empty. I did not run Spark next to the serve stack. Instead `scripts/push_stage_metrics.py` re-sent the records of the last real runs (`reports/stage_metrics/*.json`, runs `20261020-161323` and `20261020-172022`), with each stage's own end time as the last-success time. Nothing is recomputed. The next real batch pushes over them.

### What I ran and measured

- `promtool check config` and `check rules`: valid, 6 rules. `promtool test rules monitoring/alerts_test.yml`: SUCCESS.
- All 9 targets `up`. Every panel of both dashboards returns data through Grafana's own query API.
- **Drift, end to end.** I started the replay at 5 simulated hours per second. `PM25DriftHigh` went pending at 10:19:18, fired at 10:20:18 and reached the backend at 10:20:28, which created exactly one retrain request (cutoff 2020-05-10 14:00, 5 cities above threshold). The ops runner was not running, so no batch started.
- **Service alerts.** I stopped the model server and sent one forecast request per second for 4 minutes. `ModelServerErrors` and `TargetDown` fired after 1 minute, `BackendErrorRateHigh` (29% 5xx) after 2. All three reached the backend webhook and, as designed, created no retrain request.
- A final `down` and `up -d` with the Stage 14 compose file: all services healthy and all 9 targets up after 35 s, 0 restarts, and the 7 stage records were still in Prometheus, so the Pushgateway file survived.
- Timings and memory are in `docs/metrics.md`. Tests: 323 passed (10 new), ruff clean.

After the tests I restarted the model server, reset the replay and put `ops/` back as it was (I removed the test retrain request and the episode file it opened), so the next real replay starts clean.

### Limits you should know about

- No per-container memory. I chose not to run cAdvisor on 8 GB. Process RSS covers the backend, the frontend and the model-server proxy; the `mlflow models serve` worker and the MLflow server are only in host memory.
- `PipelineStageFailed` and `ForecastErrorHigh` are tested with promtool, not live: I would have had to fake a failed stage in the real Pushgateway, or wait for the MAE ratio to cross 1.5, which it never does on this replay (Part 10).
- Alertmanager has one receiver, the backend. Nobody is emailed or paged. The backend log and the console are where an alert is seen.
- Screenshots of the dashboards and of a fired alert still need a browser on your desktop: Grafana at http://localhost:13000, alerts at http://localhost:19090/alerts.

### How to run it

```
docker compose --profile serve up -d          # Prometheus :19090, Grafana :13000, Alertmanager :19093
PYTHONPATH=. .venv/bin/python -m scripts.push_stage_metrics   # optional: re-send last stage numbers
docker run --rm --entrypoint promtool -v $PWD/monitoring:/m:ro prom/prometheus:v3.5.0 test rules /m/alerts_test.yml
```

### Viva questions I prepared

**1. Why a Pushgateway for the pipeline and not a scrape?**
A stage lives for seconds to minutes. Prometheus might not scrape it once before it exits. The stage pushes its final numbers and the Pushgateway holds them until Prometheus collects them.

**2. Why is the Pushgateway in both profiles?**
The batch must not run next to the full serve stack. If the Pushgateway were only in `serve`, the batch would push to nothing. It is 22 MiB, and its file means the numbers survive until Prometheus is back.

**3. Why is the drift rule in the backend and not in PromQL?**
It needs per-city thresholds, a vote over 6 cities and an exclusion for Kolkata. In PromQL that would be a copy of the Python rule that could disagree with it. The backend exports one gauge and the alert only watches that.

**4. How do you know the alerts work, not just that the config is valid?**
promtool unit tests check the expressions on known input, and I fired four alerts on the live stack and saw them reach the backend, with timings.

**5. Why 15 s refresh?**
Scrapes are every 15 s (the machine limit). A faster refresh redraws the same data. 15 s is near real time for air quality, which changes by the hour.

**6. Why does only one alert retrain?**
A model-server outage or a 5xx burst is not a data problem. Retraining would not fix it and would cost 2.5 GB of RAM while the service is already in trouble.

## Part 15: Stage 15, security

### What I built

| File | What it does |
|------|--------------|
| `scripts/make_certs.sh` | Makes a small local CA and one server certificate signed by it, in `certs/` (gitignored, keys `600`). Valid for `localhost`, `127.0.0.1`, `backend`, `frontend` and any extra names or IPs given as arguments. I ran it with the VM's address, `192.168.64.7`. |
| `docker/tls_proxy/Caddyfile` | Caddy in front of Streamlit. HTTPS on host port 443 with my certificate; host ports 80 and 8501 answer with a `301` to `https://`. |
| `docker-compose.yml` | New `tls-proxy` service (64m, runs as my user). The frontend no longer publishes 8501. The backend gets the certificate and serves HTTPS; its health check uses `https` and `--cacert`. The frontend gets `BACKEND_URL=https://backend:8000` and `BACKEND_CA_FILE`. Prometheus and Alertmanager get `ca.crt`. Alertmanager reads the API key from `.env`. |
| `monitoring/prometheus.yml`, `monitoring/alertmanager.yml` | The backend job and the webhook use `https` and check the certificate against `ca.crt`. |
| `src/backend/main.py` | Default certificate paths are now `/certs/server.*`. The HTTPS-or-HTTP logic was already there from Stage 10. |
| `src/frontend/client.py` | A failed certificate check is logged with a hint about `BACKEND_CA_FILE`. The user still sees the same plain "the backend does not answer" message. |
| `tests/test_security.py` | 11 tests: the script's certificate verifies against its CA and has the right names; keys are owner-only; `certs/` and `.env` are gitignored; the frontend client works over real TLS with the CA and fails with the plain message without it; the backend picks HTTPS when the files exist; compose, Prometheus and Alertmanager use HTTPS; every container is non-root; secrets only come from `.env`. |

Two parts were already in place before this stage: the API key check uses `hmac.compare_digest` (constant time, Stage 10), and the 401-without-key test (`test_ops_requires_key`, 30 cases: no header, wrong key, no `Bearer`, `Basic` and an empty key, on all six ops calls). All my images already ran as user `app`.

**Why a CA and not one self-signed certificate.** Both are self-made. With a CA, the frontend, Prometheus, Alertmanager and the health check all verify the backend's certificate properly, and nothing in the project turns verification off. It also means a browser needs to import one file, `certs/ca.crt`, to stop warning.

**Why Caddy and not Streamlit's own TLS.** Streamlit has `server.sslCertFile`, and I looked at it first. The problem is that it cannot answer plain HTTP on the same port. Everyone, me included, has been opening `http://localhost:8501`, and with Streamlit's TLS on that address gives an empty error page. That is exactly the confusing error the user should not see. Caddy redirects it to `https://localhost`. The cost is one more container, 12.6 MiB.

**Secrets.** Before this stage, the ops key lived in `.env` and in a second file, `monitoring/secrets/ops_api_key`, because Alertmanager cannot read environment variables in its config. Now the Alertmanager entrypoint writes the key from `.env` to `/tmp/ops_api_key` inside the container (mode `600`, user `nobody`) and starts Alertmanager. I checked that the old file held the same key and deleted it, so `.env` is the only copy.

**Non-root.** My five images use `USER app`. The Prometheus, Alertmanager, Pushgateway and node-exporter images run as `nobody`, Grafana as `472` (checked with `docker image inspect`). The Caddy image runs as root, so compose runs it as my user, and Caddy listens on 8443 and 8080 inside the container; Docker maps 443 and 80 to them.

### What went wrong

**Pages through the proxy took 42 ms.** Streamlit's own health endpoint answered in 0.3 ms inside its container, but 42 ms through Caddy. The first request on a new connection was fast and every later one was slow, which pointed at reused connections between Caddy and Streamlit: a Nagle and delayed-ACK stall. I turned off keep-alive from Caddy to Streamlit. A new connection on the Docker network costs well under a millisecond, and the p50 dropped to 1.0 ms. The websocket, which carries the actual page updates, is one long connection and is not affected.

**The proxy looked close to its memory limit.** Under the slow config it showed 49 MiB of 64m, and I raised the limit to 96m. After the keep-alive fix it used 12.6 MiB, so I put it back to 64m. The 49 MiB was probably the pile of held connections.

**A test of mine was too broad.** The "secrets come only from `.env`" test flagged `TLS_KEY_FILE` because the name contains `KEY`. That is a path, not a secret. The test now looks only at names ending in `API_KEY` or `PASSWORD`.

### What I ran and measured

On the live stack:

```
$ curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:8501/
301 https://localhost/
$ curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost/forecast
301 https://localhost/forecast
$ curl -s --cacert certs/ca.crt https://localhost/_stcore/health
ok
$ curl -s https://localhost/            # no CA, as a browser sees it first
exit 60 (certificate not trusted)
$ curl -s --cacert certs/ca.crt https://localhost:8000/health
{"status":"ok","model_server":"up","model_version":"4",...}
$ curl ... https://localhost:8000/ops/drift                          -> 401
$ curl ... -H "Authorization: Bearer nope" .../ops/drift             -> 401
$ curl ... -H "Authorization: Bearer $OPS_API_KEY" .../ops/drift     -> 200
$ curl http://localhost:8000/health     # plain HTTP to the HTTPS port
exit 52 (empty reply)
```

- `openssl s_client` to the backend: TLS 1.3, `TLS_AES_256_GCM_SHA384`, verify return code 0.
- The Streamlit websocket upgrades through the proxy (`101`). From inside the frontend container, `BackendClient` read `https://backend:8000` and `/certs/ca.crt` and got the city list.
- Prometheus: all 9 targets `up`, the backend scraped as `https://backend:8000/metrics`.
- Alertmanager: I posted a test alert (`TLSWebhookTest`, no `action` label). The backend logged it and answered `POST /ops/alerts` with 200 over HTTPS. No retrain request was created, as designed.
- The VM address works too: `https://192.168.64.7/` returned 200 with the CA.
- Cold start (`down`, then `up -d`): the page answered over HTTPS after 25 s, 9 of 9 targets up, 0 restarts.
- Latency and memory are in `docs/metrics.md`. Over an open connection the forecast takes the same 8.7 ms as over plain HTTP. Tests: 334 passed (11 new), ruff clean.

I did not get a browser screenshot of the page over HTTPS. The VM has Firefox but not `certutil`, so I could not make a headless profile that trusts the CA. The websocket upgrade and the frontend container's call to the backend cover the same path.

### How to run it

```
scripts/make_certs.sh 192.168.64.7          # once; add the VM's IP or name so other devices can use it
docker compose --profile serve up -d
# open https://localhost  (http://localhost and http://localhost:8501 redirect there)
```

**The browser warning.** On the first visit the browser says the connection is not private, because it does not know my CA. For a demo, "Advanced" then "Proceed to localhost" (Chrome) or "Accept the risk and continue" (Firefox) works and is remembered. To remove the warning for good, import `certs/ca.crt` once as a trusted authority: in Chrome, Settings > Privacy and security > Security > Manage certificates > Authorities > Import; in Firefox, Settings > Privacy & Security > Certificates > View Certificates > Authorities > Import, and tick "trust this CA to identify websites". The user manual (Stage 18) will show this with screenshots.

If you regenerate the certificates, restart the stack so every service loads the new files.

### Limits you should know about

- The browser warning stays until `ca.crt` is imported. A certificate every browser trusts needs a public domain and an outside CA, which the no-cloud rule rules out.
- Inside the compose network, the model server, MLflow and the exporters still speak plain HTTP. That traffic stays on this machine and carries no secret. The ops key travels only to the backend, and that hop is encrypted.
- The console's links to MLflow, Grafana and Prometheus are still `http://localhost:...`. Those tools are for me as the operator, and Grafana is read-only for anonymous users.
- Port 8000 (the backend) is published for API clients and answers only HTTPS. A browser pointed at `http://localhost:8000` gets an empty reply. Non-technical users never go there; they use the frontend.
- The certificates last 825 days, the longest browsers accept. `scripts/make_certs.sh` makes new ones.

### Viva questions I prepared

**1. What does TLS protect here, exactly?**
The traffic between the browser and the system, and between the frontend and the backend. The second one matters because the console sends the ops key on that hop. Without TLS, anyone on the network could read the key.

**2. A self-signed certificate is "not secure", the browser says so. Why use it?**
The browser says it does not know who signed it, not that the encryption is weak. The encryption is TLS 1.3 either way. The services know my CA and check it, so for them the identity check is real. For the browser, importing `ca.crt` once gives the same.

**3. Why compare the key in constant time?**
A normal `==` stops at the first wrong character, so a wrong guess that starts right takes a little longer. Over many tries that timing could leak the key. `hmac.compare_digest` takes the same time either way.

**4. Why a proxy instead of TLS in Streamlit?**
Streamlit cannot redirect plain HTTP. With its TLS on, the old address shows an empty error page. Caddy gives a redirect, so a user who types `localhost:8501` still lands on the forecast.

**5. Why must containers not run as root?**
If someone breaks into a service, they get that user's rights. Root inside a container is much closer to root on the host, especially with mounted folders. As a normal user, files they write on my mounts belong to me, and system paths are off limits.

**6. Where are the secrets, and how do you know none are in git?**
Only in `.env`, which is gitignored together with `certs/`. A test checks both with `git check-ignore`, and another checks that every key and password in compose is a `${...}` from `.env`.

## Part 16: hiding Streamlit's developer controls, and Stage 16 (CI)

### First, a small UI fix (commit `d2a3cf9`)

The page showed Streamlit's "Deploy" button and the three-dot menu in the top right. A
non-technical user has no use for either, and "Deploy" invites a click that leads nowhere useful.
I added `.streamlit/config.toml` with `client.toolbarMode = "minimal"` and copy it into the
frontend image.

I picked `minimal` over `viewer`. `viewer` removes the developer items (rerun, clear cache,
Deploy) but keeps the menu itself with settings and print. `minimal` shows only options set
through `st.set_page_config`, and my app sets none, so the menu disappears too. Inside the
rebuilt container, `config.get_option("client.toolbarMode")` returns `minimal`, and a test
checks both the config file and the `COPY` line in the Dockerfile.

### What I built

| File | What it does |
|------|--------------|
| `scripts/ci.sh` | The CI run. Steps: `ruff check`, `ruff format --check`, `pytest` (writes `reports/ci/junit.xml`), then `dvc status` (does `dvc.lock` match the code, params and data?) and `dvc status -c` (is every output in `dvc.lock` in the local DVC remote?). With `--repro` it runs `dvc repro` and `dvc push` before the two DVC checks. Prints a PASS/FAIL table with times and saves everything to `reports/ci/last_run.log`. |
| `.pre-commit-config.yaml` | The git hook: ruff check, ruff format, the whole pytest suite, and a guard that fails if data, the candidate model, `certs/`, `mlflow.db` or `.env` is staged. |
| `tests/test_ci.py` | 6 tests: the script parses, `--help` and bad options, `--repro` refused when a (fake) `docker` reports running containers, the order of the steps, and the hook config, including which paths the guard catches. |

A few choices to explain:

- **No cloud CI.** The project forbids cloud platforms, so GitHub Actions is out. The script
  is the CI, and I run it before each stage commit. The hook is the part that runs on every
  commit by itself.
- **The hooks are `repo: local` and run through `uv run --frozen`.** pre-commit normally
  downloads each hook's own copy of ruff from GitHub. A local hook uses the ruff and pytest
  versions pinned in `uv.lock`, so the hook and `ci.sh` cannot disagree, and it needs no
  network.
- **pytest is in the pre-commit hook, not pre-push.** The repository has no git remote, so a
  pre-push hook would never run. The full suite takes about a minute. To keep commits of docs
  alone fast, the hook runs pytest only when code or a config file the tests read is staged.
- **The DVC checks are not in the hook.** I often commit code first and rerun the pipeline
  after (Stage 8 has a "code" commit and a "results" commit). A hook that demands an
  up-to-date `dvc.lock` would block that. `ci.sh` checks it before a stage is closed.
- **`--repro` trains only if lint and tests passed.** Broken code should not produce a model.
  It also refuses to start while the serve stack is up, because Spark and the serve containers
  together do not fit in 8 GB.
- **The DVC run is marked.** `ci.sh` sets `PIPELINE_TRIGGER=ci` and `PIPELINE_RUN_ID=ci-<time>`,
  so the console's run table and the MLflow run show where the run came from.

### What went wrong

**The pipeline was out of date and I had not noticed.** The first check-only run failed on
`dvc status`: every stage was stale because `src/common/stage_runner.py` changed in Stage 14 (an
optional argument for re-pushing old stage records). Every stage lists `src/common` as a
dependency, so DVC is right to flag it, even though the change does not affect any output. This
is the kind of problem CI is for. `--repro` reran the whole pipeline.

**The DVC remote held only the raw data.** `dvc status -c` listed 50 files from `data/interim`,
`data/features` and `models/candidate` that were only in the local cache. In this state, an old
commit could not be rebuilt with `dvc pull` without Spark running again. `--repro` now ends with
`dvc push`, and the remote is in sync.

**`dvc status` exits 0 even when stages are stale.** My first draft used its exit code, so it
would have passed. The script now reads the message and passes only on "Data and pipelines are
up to date" or "are in sync".

**Commit demo.** I staged a file with an unused import and no docstring. The hook stopped the
commit with ruff's D100 and F401 errors, and `git log` was unchanged. The guard also failed
`pre-commit run no-data-or-secrets --files certs/ca.crt .env data/raw.dvc` on the first two
files and let `data/raw.dvc` through.

### What I ran and measured

Check-only run at `f8fde15`, serve stack up: ruff and format pass, 341 tests pass, `dvc-status`
FAIL, `dvc-remote` FAIL, exit 1, as expected.

`scripts/ci.sh --repro` with the stack up: refused, exit 3. After
`docker compose --profile serve stop`:

```
== summary (commit f8fde15)
ruff           PASS     0s
ruff-format    PASS     0s
pytest         PASS    55s
dvc-repro      PASS    97s
dvc-push       PASS     0s
dvc-status     PASS     1s
dvc-remote     PASS     0s
CI PASSED
```

All 7 stages ran. The new candidate scored a mean MAE of 6.467, the same as champion v4 on the
same window, because the data and cutoff did not change. The gate rejects ties, so v4 stays
champion and `reports/register.json` now records a rejected candidate. That is the gate doing
its job, not a failure. JUnit: 341 tests, 0 failures, 0 errors, 0 skipped. Stage times and
memory are in `docs/metrics.md`. I then started the serve stack again: all containers healthy,
`/health` reports model version 4, and the page answers over HTTPS.

### How to run it

```
uv run pre-commit install                       # once per clone; then every commit is checked
scripts/ci.sh                                   # lint, tests, DVC checks (about 1 min)

docker compose --profile serve stop             # full run: free the memory first
scripts/ci.sh --repro                           # + dvc repro and dvc push (about 2.5 min)
docker compose --profile serve up -d
```

The result is in `reports/ci/last_run.log` and `reports/ci/junit.xml`; Stage 17's test report
reads the XML.

### Limits you should know about

- **CI runs only when I run it.** No server watches the repository. The hook runs on every
  commit, but `git commit --no-verify` skips it, and a new clone needs `pre-commit install`.
- **`dvc.lock` changes on every Spark rerun, even when the data does not.** Spark names its
  Parquet part files with a random ID, so the directory hash changes, and the candidate model
  carries its new MLflow run ID. That is why 50 files were pushed. The MLflow data version tag is a hash of the feature values (Stage 7), so it stays the
  same across reruns.
- **A change to `src/common` reruns everything,** including the two-minute Spark stages, even
  when the change cannot affect any output (here, a helper used only by
  `scripts/push_stage_metrics.py`). Narrower dependencies would avoid it, but I
  kept one entry per folder so that a new shared helper can never be missed.
- **`reports/ci/` holds only the last run.** Earlier runs are in git history if they were
  committed.

### Viva questions I prepared

**1. Where is your CI? I don't see GitHub Actions.**
The rules forbid cloud platforms. `scripts/ci.sh` does what a hosted CI job would do (lint,
tests, rebuild the pipeline, check that code, data and models agree), and the pre-commit hook
runs the fast part on every commit. The output is saved as a log and as JUnit XML.

**2. What does `dvc status -c` prove?**
That every file `dvc.lock` names is in the DVC remote. Git holds the hashes and the remote holds
the files. Together they mean I can check out any commit and get back its exact data and model
with `dvc pull`.

**3. Your CI retrained the model. Did it change what is served?**
No. The candidate tied with v4 (6.467 MAE on the same window), and the gate only promotes a
candidate that is strictly better. The served model is still v4. A CI run can only change the
served model through the same gate as a drift retrain.

**4. Why is the full pytest suite in a pre-commit hook? Isn't a minute too slow?**
With no git remote, pre-push never fires, so the hook is the only automatic gate. It skips
pytest when only docs are staged, and the one-minute wait is on commits that change code,
where a broken test is worth catching.

**5. Why does `--repro` refuse to run with the stack up?**
Spark needs a 2 GB driver, and the serve stack uses most of the rest of the 8 GB. Running both
risks the kernel killing a container mid-request. The script checks with `docker compose ps` and
exits with code 3 instead.

### Next: Stage 17

Testing docs: a test plan with numbered cases and acceptance criteria, and a test report with
passed/failed counts from `reports/ci/junit.xml`.

## Part 17: Stage 17, testing docs, user manual, README and the final audit

### What I wrote

| File | What it is |
|------|------------|
| `docs/test_plan.md` | Scope, the three test levels (unit, integration, end to end) plus static checks, the test machine and versions, how to run, 7 acceptance criteria with a measurable pass rule each, and 65 numbered cases: TC-01 to TC-48 cover every pytest function, E2E-01 to E2E-17 the drills done on the real stack |
| `docs/test_report.md` | 341 run, 341 passed, 0 failed (from `reports/ci/stage17/junit.xml`), per file; each E2E check with its evidence; each acceptance criterion with numbers; the two defects this run found |
| `docs/user_manual.md` | For a non-technical user: starting the app, the certificate warning, the forecast page, the colours and advice, the error messages, the console and its buttons. 13 marked screenshot placeholders with file names |
| `README.md` | What it is, a short architecture diagram, the one-command start, measured numbers, how to reproduce a model from its run ID, and what broke |
| `docs/rubric_checklist.md` | Every rubric and guideline line mapped to a file, command, test or screenshot; missing and weak items at the top |

`docs/metrics.md` has a new Stage 17 section and `docs/LLD.md` lists the two new backend environment variables.

### What I ran again today

- `scripts/ci.sh`: ruff and format pass, 341 tests pass in 44.6 s, `dvc status` and `dvc status -c` clean.
- `python -m scripts.replay`: 0 drift hours in 2016-2019, 661 in 2020, exit 0.
- 600 forecast calls over HTTPS: p95 13.5 ms (reused connection) and 16.2 ms (new connection), all 200.
- Reproducibility: champion v4's run tags lead to a rebuild (the Stage 16 CI run) with the same data and feature hashes, the same MAE and byte-identical LightGBM files.
- Rollback drill through `POST /ops/rollback` on the live stack, then undo. The registry is back to champion 4, previous 1.

### What went wrong

**Rollback through the app had never worked.** My first `POST /ops/rollback` hung. MLflow logged `attempt to write a readonly database`. Compose mounted `mlflow.db` as a single file, so Docker made the parent folder inside the container `root:root`, and SQLite cannot write its journal there. Reads work, which is why nothing earlier showed it. As far as I can tell every earlier registry write came from a host process. The fix mounts the project folder into the `mlflow` container. The cost: that container can now read the whole project, `.env` included, like the pipeline container already could.

**A rollback I had given up on was applied 4 minutes later.** I killed the hung `curl`, but the backend went on retrying with MLflow's default back-off (several minutes). Once the mount was fixed, that call went through at 07:46:35 and moved the champion from 4 to 1 in the middle of my clean drill. That confused me for a few minutes, because "rollback to 4" then answered 200 when 4 should already have been the champion. The backend log showed a "Champion 4 -> 1" I had not sent. The backend now sets `MLFLOW_HTTP_REQUEST_MAX_RETRIES=2` and `MLFLOW_HTTP_REQUEST_TIMEOUT=10`. With MLflow stopped, a rollback fails after 5 s and nothing changes later. I only recreated the `mlflow` and `backend` containers. The rest of the stack kept running.

**My architecture diagram was wrong about the runner.** It said the runner starts the batch container. The code runs `dvc repro` on the host, and the pipeline container has never run a full pipeline. I corrected `docs/architecture.md` and say so in the checklist.

**I ran the replay without `--with-mae` first.** That rewrote `reports/drift_replay.json` without its MAE section. The drift numbers were identical, so I restored the committed file.

### Still open (top of `docs/rubric_checklist.md`)

1. Docker Hub: the multi-arch push needs your login and QEMU (sudo).
2. Screenshots: the 13 placeholders in the user manual, Grafana, a fired alert.
3. A browser and narrow-window check of both pages.

### How to take the screenshots

The serve stack is running. Open `https://localhost` on your desktop browser (accept the warning or import `certs/ca.crt`). Each placeholder in `docs/user_manual.md` says what to show and the file name to save it as, in `docs/screenshots/`. For the drift and alert shots, start the replay from the console at 5 simulated hours per second; drift appears after about 2.5 minutes, and the alert fires in Prometheus (`http://localhost:19090/alerts`) a minute later. The ops runner is not running, so no retrain will start. Afterwards press Reset replay. For a clean state, also delete the new request file the alert creates in `ops/requests/` (keep `rt-20261020-172013.json`, the Stage 11 record) and `ops/episode.json`.

### Viva questions I prepared

**1. What is the difference between your unit, integration and end-to-end tests?**
Unit tests use fakes and small inputs and need nothing running. Integration tests use the real library on a small scale: a real Spark session, a real MLflow store in a temp file, a real TLS server, the real Streamlit pages. End-to-end checks use the real data and the running stack, and most of them I ran as recorded drills.

**2. How do you know rollback works?**
I moved the champion from 4 to 1 through the same endpoint the console uses, saw forecasts answer with version 1 five seconds later, then undid it and saw version 4 come back. Doing that drill is how I found that the compose set-up could not write the registry at all.

**3. Your test passed in pytest. Why did it fail on the stack?**
The pytest tests use a temporary SQLite file that the test process owns. The bug was in how Docker mounted the file into the MLflow container, which no unit test can see. That is why the plan has end-to-end checks, and why I ran them again instead of copying old results.

**4. How do you prove a result is reproducible?**
Start from the run ID. Its tags give the commit, the cutoff and the data version. A rebuild with that code, data and cutoff gave the same data hash, the same MAE to every printed digit, and model files identical byte for byte. That only works because I made LightGBM deterministic in Stage 7.

**5. 341 tests pass. What do they not cover?**
A real browser, a real phone, concurrent load, a real failed smoke check, and the batch container. The report says this in its last section.

## Part 18: fixing the final audit (paused 2026-10-27, resume 2026-11-03)

(Finished on 2026-11-03, see Part 19.)

`docs/final_audit.md` found 10 things I could fix (its section (a)). I fixed them one commit each and paused part-way. The table "Status of the fixes" at the top of that file is the exact state; this part says what I did and how to resume.

### Done

- **Pushgateway persistence** (`ba0473a`). The image runs as `nobody`, and the volume on `/data` was root-owned, so the save file was never written. The volume is now on `/pushgateway`, the image's own folder. A probe metric survived a full `down`/`up`.
- **Ops runner pauses containers around the batch** (`1c95beb`). It stops the frontend and Grafana before its memory check and starts exactly those again when `dvc repro` ends, also when it fails or memory is short. I checked live that `docker compose stop frontend` leaves the TLS proxy up. The proxy now answers 503 with a "Back in a few minutes" page instead of an empty 502. Live check with the real runner: both containers were stopped and started again within 2.3 s, and `params.yaml` was unchanged (`docs/metrics.md`, "Final audit fixes").
- **How to start the runner** (`957dea2`, `d30d9ab`): HLD and the user manual.
- **OpenAPI error responses** (`a66701c`), **console** (short replay time, "Failed runs" table, `5ccdd24`), **LLD trigger values** (`e2046a6`), **architecture diagram and the other doc inconsistencies** (`ed87793`), **test plan rows** for the new tests (`7dae2c9`).
- **A deliberate failure for the console demo.** This was not a real defect. I lowered the PM2.5 ceiling in `params.yaml` from 1000 to 500 and ran `dvc repro validate` with `PIPELINE_RUN_ID=demo-failure-20261027`. The stage failed as designed: "4 hard check(s) failed: ... city_hour/values_below_ceiling: PM2.5 > 500 in 2120 rows ...". I then restored `params.yaml` and `reports/validation.json` from git. The record is in `reports/runs.jsonl`, and its status was pushed to the Pushgateway.

### Not finished

- **`scripts/bootstrap.sh`** for a fresh clone is written but not tested. It sits with its README and user-manual run steps, the `.env.example` cleanup and the new E2E-18 to E2E-22 test-plan rows in `git stash`, under "WIP final-audit fix a2 ...". `.env.example` had container addresses such as `MODEL_SERVER_URL=http://model-server:5001`, which the host tools load from `.env` and cannot resolve. The stash removes them.
- **MLproject in a fresh environment.** `mlflow run . -e main --env-manager uv` rebuilds the environment from `uv.lock` (not from `python_env.yaml`) and downloads everything. Over this VM's slow link it had not finished downloading after several minutes, so I stopped it. It never trained.
- **A real `dvc repro -f`** to refill the pipeline dashboard and clear the failed validate status: not started.

### What went wrong

- I wrote in HLD that compose stops the TLS proxy together with the frontend. I tested it before committing: it does not. I corrected the docs, and the runner still compares running containers before and after the stop, in case another Compose version behaves differently.
- I misremembered which PROGRESS parts held two numbers I moved into `metrics.md`, and guessed how they were measured. I checked and corrected both before committing.
- The shell's safety check failed on and off all afternoon. That is why the work took longer than the code needed.

### How to resume on 3 Nov

1. `git stash list`, then `git stash pop` the "WIP final-audit fix a2" entry.
2. Stop everything (`docker compose --profile serve down`). Clone into `/tmp`, run `scripts/bootstrap.sh`, `docker compose --profile serve up -d`, smoke-test, then `down -v` and delete the clone. The clone uses the same host ports, so the main stack must stay down. Commit fix a2 if it passes.
3. MLproject: retry with `UV_HTTP_TIMEOUT=900`, or accept it as WEAK and say why.
4. With only the Pushgateway up (`docker compose --profile batch up -d pushgateway`), run `PIPELINE_TRIGGER=manual uv run --frozen dvc repro -f`. Then `dvc push`, and commit `dvc.lock` and `reports/`.
5. Bring the stack up and check that the console shows `demo-failure-20261027` and that the pipeline dashboard has data.
6. `scripts/ci.sh`. Update `test_report.md` (now 350 tests), the README test count, the rubric table in `final_audit.md`, and PLAN.

## Part 19: finishing the final-audit fixes (2026-11-03)

I resumed the list from Part 18. All of section (a) in `docs/final_audit.md` is now done, and the re-audit is in that file.

### What I did

- **Bootstrap in a clean clone** (`d7e0b03`). I restored the stash, stopped the stack and cloned into `/var/tmp/aq-clone`. Part 18 said `/tmp`, but `/tmp` on this VM is a RAM disk (tmpfs, 3.7 GB). A venv, the raw data and the DVC cache there would have taken memory from Spark. The folder name also matters: Compose names the project after it, and a clone called `da3408-project-aq-forecast` would have shared the main stack's volumes, so `down -v` would have deleted them. `scripts/bootstrap.sh` ran with exit 0 in 7 min 20 s. Six of those minutes were `uv sync` downloading 24 packages that were not in uv's cache, and the pipeline took 75 s. The serve stack was healthy in about 25 s, a forecast answered 200, all 9 targets were up, and keyed ops calls worked. Then `down -v`, and I deleted the clone. The README had said "about 2 minutes", so I changed it to the measured time.
- **A real pipeline run** (`05a7b61`). With only the Pushgateway up: `PIPELINE_TRIGGER=manual dvc repro -f`, 75.5 s, all 7 stages. The candidate tied v4 (6.467) and was rejected. All 7 stage statuses went to 1, which replaced the `validate 0` from the demo failure, and the pipeline dashboard has data again.
- **MLproject in a fresh environment** (`5785004`). It built a new environment from `uv.lock` in 1 s, because the clone test had just filled uv's cache. It trained, then crashed when it logged the run (defect D-3 in the test report). `mlflow run` puts its run in the Default experiment and `train.py` sets `aq-pm25`. With `--experiment-name aq-pm25` it worked, with the same MAE and byte-identical LightGBM files as the pipeline. I documented the flag and did not change `train.py`, because both paths should log to one experiment.
- **Stale images.** The re-audit found that the backend and frontend images were from 2026-10-21. The console and OpenAPI fixes of 2026-10-27 were committed and tested, but not running. I rebuilt both images and restarted the two services. The console now shows the failed runs live. The README has `up -d --build` for after a code change.
- **Re-audit and docs.** `final_audit.md` (status table, re-audit, tally), `test_report.md` (350 tests, E2E-18 to E2E-22, D-3), README test count, `rubric_checklist.md`, `metrics.md`, this file and PLAN.

### What went wrong

- The crashed MLproject run pushed `train 0` to the Pushgateway, which would have fired `PipelineStageFailed`. The successful retry pushed `1` over it. The failed run stays in `runs.jsonl` and shows in the console. It is a real failure, so I left it there.
- The MLproject run overwrote `models/candidate` and `reports/train_metrics.json`. I restored both with `dvc checkout --force` and `git checkout`, after keeping a copy to compare. `dvc status` is clean.
- I guessed an ops path that does not exist (`/ops/models`) and the wrong auth header during the clone smoke test. The LLD says `Authorization: Bearer`, and with that every call worked.
- I did not notice the stale images on 2026-10-27, because I checked those fixes with unit tests and not on the running stack.

### State I left

The serve stack is running on the rebuilt images. The ops runner is not running. Start it with `uv run --frozen python -m src.ops.runner`. Registry: champion 4, previous 1. What is left is all mine to do (final audit (b)): screenshots and the browser check, Docker Hub and the multi-arch images, the GitHub remote, the demo video.

### How to run what I checked

```
scripts/bootstrap.sh                                   # fresh clone, once (stack must be down)
docker compose --profile serve up -d --build           # rebuild the images after a code change
mlflow run . -e main --env-manager uv --experiment-name aq-pm25
PIPELINE_TRIGGER=manual PIPELINE_RUN_ID="manual-$(date +%Y%m%d-%H%M%S)" \
    uv run --frozen dvc repro -f                       # only the Pushgateway up
```

## Part 20: replay-clock note, screenshot links, test count, full pipeline run (2026-11-05)

### What I did

- **Replay-clock note on the Forecast page** (`2a0444b`). Under the date, the page reads `replay_running` from `GET /health`. It says "Demo clock is paused. Start the replay in the Pipeline console to move time forward." or "Replay running". If `/health` fails, it leaves the note out and still shows the cards. 3 new tests. I rebuilt only the frontend image (`up -d --build --no-deps frontend`), because the disk was full. With permission, I pruned Docker's unused build cache, which freed 2.9 GB. Rendered with `AppTest` inside the running container against the live backend, the page showed the right note in both replay states. I left the replay stopped, as I found it.
- **User manual screenshots** (`6f3bb7c`). The placeholders are now image links to `docs/screenshots/<name>.png`. Placeholders 02 and 03 (certificate warning, CA import) became short written steps. The PNG files are not taken yet.
- **Test count.** `scripts/ci.sh` at `6f3bb7c`: 353 passed, 0 failed, in 30 files (`test_frontend.py` 21 to 24), DVC clean and in sync. I copied that run into `reports/ci/final/`. `test_report.md`, the README, `rubric_checklist.md` and `final_audit.md` now say 353. Older numbers in this file and in `final_audit.md` (341, 350) stay as they were, because they are what those runs measured on their day.
- **A full pipeline run for the console.** The console's latest run was `20261103-173624`, the train-only MLproject test, so 6 of 7 stages showed not run. I stopped the serve stack, started only the Pushgateway and ran `PIPELINE_TRIGGER=manual dvc repro -f`. All 7 stages passed in 1 min 24 s. But each stage wrote its own `run_id`, because the stage runner falls back to a timestamp when `PIPELINE_RUN_ID` is not set. The console groups by `run_id`, so its latest run would have been register alone. The 2026-11-03 run in Part 19 had the same problem. The ops runner and `ci.sh` set `PIPELINE_RUN_ID`, and the manual command did not. I ran it again with `PIPELINE_RUN_ID=manual-20261105-174821`: 1 min 16 s, about 1 GB peak memory. Stage times were ingest 8.4 s (411,200 rows/s), validate 30.0 s, features 10.8 s, train 19.7 s, evaluate 0.6 s, test 0.0 s and register 0.3 s. The candidate tied v4 at a mean MAE of 6.467 and the gate rejected it, so v4 is still champion and v1 previous. The console shows all 7 stages green. The 7 one-stage records from the first try stay in `runs.jsonl`, because they were real runs. `dvc push` sent 16 files. I committed the new `dvc.lock` and the changed reports. `runs.jsonl` stays out of git, because it is runtime data and is in `.gitignore`. The manual command in the README and below now sets `PIPELINE_RUN_ID`.

### State I left

The serve stack is running and healthy. Registry: champion 4, previous 1. The replay is stopped at 25 Mar 2020, 00:00. The ops runner is not running. Bringing the stack up after the pipeline run moved MLflow and the model server to the `aq-mlflow` and `aq-model-server` images I rebuilt today by accident. Those images come from the same Dockerfiles, and both services are healthy. About 1.5 GB of disk was free right after the frontend rebuild and 6.6 GB later in the day. A full `up -d --build` rebuilds four images of 0.8 to 1.3 GB, so I check `df -h /` first.

## Part 21: rollback message with MLflow down, pipeline in the batch container (2026-11-05)

### What I did

- **Rollback with MLflow down** (`3dd6081`, rubric checklist item 8). The registry used to read any MLflow error as "alias not set", so with MLflow down a rollback said "No previous version to roll back to". Now only MLflow's not-found codes mean "not there". Any other error during a rollback raises `RegistryUnavailableError`, and the backend answers 503 `REGISTRY_UNAVAILABLE`, which is a new code in the LLD. Serving lookups stay lenient, so forecasts still work without MLflow. 5 new tests. Live, after rebuilding only the backend image, with the `mlflow` container stopped: 503 in 4.4 s and 4.9 s. The aliases were unchanged after MLflow came back.
- **Pipeline in the batch container** (item 7, E2E-23). With the serve stack stopped and only the Pushgateway up, `docker compose --profile batch run --rm pipeline dvc repro -f` failed twice before it worked (defect D-4). The container runs as my uid, which the image's `/etc/passwd` does not have. DVC failed in `getpass.getuser()`. With `USER` set, Spark's Hadoop login failed next, because it reads the user database directly. Compose now mounts the host's `/etc/passwd` and `/etc/group` read-only. That needs no image rebuild, so the Docker Hub image is still current. Run `container-20261105-214229`: all 7 stages in 74.4 s, peak memory 2.39 GiB of the 2.5 GiB limit. The candidate tied v4 at 6.467 and was rejected, so v4 is still champion and v1 previous. `dvc push` sent 18 files. The serve stack is back up and healthy, and the console shows this run with all 7 stages green.
- **Counts.** 358 tests now (`test_registry.py` 6 to 9, `test_backend.py` 95 to 97). The docs that quote the current count say 358.

### What went wrong

- My first CI run after the rollback fix failed `dvc status`. `src/common` and `registry.py` are stage dependencies, so `dvc.lock` stayed stale until the pipeline ran again. I committed the fix first, so the container run would record a clean commit, and I committed the run separately.
- The Spark attempt for D-4 left a real `ingest failed` record in `runs.jsonl`, and pushed `ingest 0` to the Pushgateway. The successful run replaced it with 1.

### State I left

The serve stack is running and healthy. Registry: champion 4, previous 1. The ops runner is not running. The pipeline container's memory margin is small: 2.39 of 2.5 GiB.

## Part 22: screenshots, browser check, cut-off replay time (2026-11-05)

### What I did

- **Screenshots.** The 11 screenshots are in `docs/screenshots/`, and every image link in the user manual resolves to a PNG. I looked at them: the API key field is masked wherever it shows, and the terminal shot shows only `docker compose ps`.
- **E2E-17 passed.** `05_forecast_mobile.png` is Firefox's responsive mode at iPhone 14 size (393 x 852): the page fits, the text wraps and the two cards stack. The final audit's three WEAK lines (Responsive, User manual exists, User manual (mandatory doc)) are PASS. The tally is 60 PASS, 0 WEAK, 0 FAIL.
- **D-5, found by the browser check.** Screenshot 08 shows the console's "Replay time" box cut off as "25 Mar, …". The audit had called this fixed on 2026-11-03, but that evidence came from Streamlit's `AppTest`, which sees values and not widths. The four status boxes are now two rows of two. A new test checks that each box sits in a half-width column, and it fails on the old layout. I rebuilt only the frontend image. Live, the four boxes are at half width and "Replay time" reads "25 Mar, 00:00".
- **Tests.** 359 of 359 (`test_frontend.py` 24 to 25). The docs that quote the current count say 359.

### What went wrong

- I trusted a structural test for a visual fault on 2026-11-03. Only a real browser showed it.

### D-5 verified

Screenshot 08 was taken again at 22:37 in Firefox at default zoom. It shows the two rows of two, and "Replay time" reads "25 Mar, 00:00" in full. D-5 is closed in the test report.

### Still open

- Section (b) of the final audit: the GitHub remote, the demo video and viva preparation, and a check on a real phone (optional).
