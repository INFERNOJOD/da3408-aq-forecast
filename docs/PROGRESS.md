# Progress Report

This file has two parts. Part 1 covers Stages 2-4 (written earlier).
Part 2, at the end, covers the housekeeping, Stage 5 and Stage 5b.

## Part 1: Stages 2, 3 and 4

Status: all three stages are done and committed. Nothing is blocked.
No sudo was used. Nothing was pushed to any remote except the local DVC folder.
The `a4-*` containers were left running. `data/raw` was not touched.

| Stage | Commit | What it delivers |
|-------|--------|------------------|
| 2. Project skeleton | `6f8ca82` | Python 3.12 environment, lint and test setup, shared helpers |
| 3. DVC | `1de6eed` | Raw data is versioned by DVC with a local remote |
| 4. Spark ingest | `2491249` | CSV files converted to Parquet, with run records |

Checks at the end: `ruff check` passes, `pytest` gives 29 passed, 0 failed, `dvc status` says up to date.

## Stage 2: project skeleton

**What was built**
- A Python 3.12 virtual environment in `.venv` (made with `uv`). Python 3.14 was too new for Spark and MLflow.
- `pyproject.toml`: the package list and the ruff and pytest settings.
- `params.yaml`: one place for settings (Spark memory, cities, cut-off date).
- `.env.example`: a template for secrets. The real `.env` is git-ignored.
- `src/common/`:
  - `config.py` loads `params.yaml` and `.env`.
  - `logging_setup.py` sets up logging the same way everywhere.
  - `errors.py` defines our own error types.

**Why:** every later stage needs the same logging, settings and error handling. Doing it once avoids copy-paste.

## Stage 3: DVC

**What was built**
- DVC started in the repo. Its remote storage is a plain folder: `/home/krish-yadav/DA3408/dvc-remote`. No cloud.
- `data/raw` is tracked by DVC. Git stores only the small `data/raw.dvc` file (it holds a hash of the data).
- The raw data was pushed to the remote.

**Why:** git is bad at big files. DVC keeps the data outside git and pins the exact version with a hash. The git commit then points to the exact data used.

**Problem found and fixed:** a broad `/data/*` rule in `.gitignore` made DVC skip `data/raw.dvc`. `dvc push` said "up to date" while the remote was empty. The rules now name the sub-folders (`/data/raw/`, `/data/interim/`, `/data/features/`).

## Stage 4: Spark ingest

**What was built**
- `src/pipeline/ingest.py`: reads the 5 CSV files with Spark and writes them as Parquet into `data/interim/`.
  - Each column has a fixed type, set in code. A bad value stops the run instead of creating silent errors.
  - After writing, it counts rows in the CSV with plain Python and compares them with the Parquet row count. They must match.
- `src/common/stage_runner.py`: wraps any stage. It records the time, row count, rows/sec, status and error message in `reports/runs.jsonl`. It also sends the numbers to the Pushgateway if `PUSHGATEWAY_URL` is set. If that server is down, the pipeline keeps going. The pipeline console will read this file later.
- `src/common/spark.py`: starts Spark with the memory limits (3 GB driver, 8 shuffle partitions).
- `dvc.yaml`: the first pipeline stage, `ingest`.
- `docs/LLD.md` row for ingest updated to match the real inputs and outputs.

**Why Parquet:** it is compressed and stored by column. Later stages read only the columns they need.

## How to run

```bash
cd /home/krish-yadav/DA3408/da3408-project-aq-forecast
source .venv/bin/activate

ruff check . && pytest -q          # lint + 29 tests (about 5 s)
dvc repro                          # runs ingest (about 8 s); skips if nothing changed
dvc dag                            # shows the pipeline graph
dvc status -c                      # data and remote in sync?
cat reports/stage_metrics/ingest.json   # last run's numbers
```

To restore the raw data on a fresh checkout: `dvc pull`.

## Measured numbers
(Full table in `docs/metrics.md`.)

| What | Value |
|------|-------|
| Rows ingested | 3,434,754 (5 tables) |
| Stage time | 8.0 to 8.4 s (3 runs) |
| Throughput | about 410,000 to 430,000 rows/sec |
| Disk size | CSV 283 MB, Parquet 65 MB |
| Peak Spark memory | about 1.2 GB (limit 3 GB) |

## Things to know
- **Time zone:** Spark runs in UTC so times keep the wall-clock values from the CSV (the data is in IST). Never convert them. Python's `collect()` shifts times to the machine's own time zone, so a test showed hours off by some. Use Spark functions like `hour()` instead.
- **Empty folders:** `backend/`, `frontend/`, `pipeline/` and `notebooks/` exist at the repo top level and are empty. Code goes in `src/`, as in `docs/LLD.md`. I left them alone. Delete them if you do not need them.
- **`reports/runs.jsonl` is git-ignored.** It is runtime data. The backend will read it.
- **Free RAM is low** (about 3.9 GB available) because of other things on the VM. Ingest peaked at 1.2 GB, so it was fine. Heavier Spark stages should be run alone.
- **The `git_commit` in run records** is the commit that was current when the stage ran, so a run made before a commit shows the older hash.
- Not done yet (later stages): MLflow, Docker, Prometheus, Grafana, FastAPI, Streamlit.

## Five likely viva questions

**1. Why Parquet instead of reading the CSV every time?**
Parquet is columnar and compressed. Our data shrank from 283 MB to 65 MB. Later stages read only the columns they need, and types are already fixed, so no text parsing is repeated.

**2. Why DVC and not Git LFS?**
DVC also records the pipeline: stages, inputs, outputs and parameters, in `dvc.yaml` and `dvc.lock`. It re-runs only what changed. It also works with a plain local folder as storage, so no cloud is needed. Git LFS only stores large files.

**3. How do you know the ingest did not lose rows?**
Two checks. Spark reads with FAILFAST, so a malformed row stops the run. Then the stage counts CSV lines with plain Python and compares with the Parquet row count. For all 5 tables they matched (3,434,754 rows).

**4. What happens if a stage fails or the monitoring server is down?**
`run_stage` catches the error, writes a "failed" record with the message to `runs.jsonl`, and raises a clear error. The pipeline console will show it. If the Pushgateway is down, a warning is logged and the pipeline still runs, because a monitoring outage should not stop data work.

**5. Why local Spark with 3 GB and 8 partitions?**
The VM has 8 GB RAM and 4 cores. Spark's default of 200 shuffle partitions creates many tiny tasks, which is slow on this small data. 8 partitions is about 2 per core. The 3 GB driver leaves room for the OS and Docker. Measured peak was 1.2 GB.

---

## Part 2: housekeeping, Stage 5 (validate) and Stage 5b (EDA)

Status: done and committed. Nothing is blocked. No sudo, no remote pushes except
the local DVC folder, `data/raw` untouched, `a4-*` containers untouched.
Checks at the end: `ruff check` passes, `pytest` gives 60 passed and 0 failed,
`dvc status` says up to date.

| Work | Commit | What it delivers |
|------|--------|------------------|
| Housekeeping and benchmark | `d5b11f2` | Empty folders removed, status column in `docs/PLAN.md`, pandas vs Spark benchmark |
| Stage 5: validate | `040e474` | 48 data checks, `reports/validation.json`, second DVC stage |
| Stage 5b: EDA | `ed7b6bd` | 8 CSV aggregates, 6 figures, `docs/eda.md` with 9 data biases |

### Housekeeping
- Deleted the empty `backend/`, `frontend/`, `pipeline/` and `notebooks/` folders.
- `docs/PLAN.md` now has a Status column. Stages 0-5b show "Done" with their commit hashes.
- **Benchmark (in `docs/metrics.md`):** pandas does the same ingest job in about 3.7 s. Spark takes about 8.2 s. **Pandas is about 2x faster on this data.** The data is small (283 MB) and fits in memory, and Spark pays about 1.2 s to start plus the cost of planning each job. Both give the same row counts. We keep Spark because the course requires it, and because it can handle data larger than memory. We have not tested that, so it is a design reason, not a measured result.

### Stage 5: validate
**What was built**
- `src/pipeline/validate.py` in two parts:
  1. Spark collects plain numbers (counts, minimums, maximums) in one pass per table.
  2. Ordinary Python functions turn the numbers into pass, warn or fail results. They need no Spark, so tests are fast.
- Hard failures stop the pipeline: wrong columns or types, empty table, missing ids or times, duplicate rows, negative values, values above the sensor ceiling, times outside 2015-2020, timestamps not on the hour, duplicate station ids, and any selected city that is short of data or missing from the replay period. Warnings are only reported: unknown AQI bucket names, too much missing PM2.5, unknown station ids.
- The report `reports/validation.json` is written even when validation fails, so the failure can be inspected. The error message names the column, the limit and the row count, for example `PM2.5 > 1000 in 12 rows`.
- Limits live in `params.yaml` under `validate:`. The second stage in `dvc.yaml` runs it.

**Result on the real data:** 48 checks, 48 passed, 0 warnings, 0 failed. The data is clean. No duplicates, no negatives, no missing ids. All 7 selected cities have PM2.5 for 99.9% to 100% of the 2,352 replay hours.

**Why this matters:** bad data would otherwise flow into training silently. A hard stop with a clear reason is what the pipeline console will show later.

### Stage 5b: EDA and data biases
**What was built**
- `src/pipeline/eda.py`: Spark counts, saved as 8 small CSV files in `reports/eda/`.
- `scripts/plot_eda.py`: draws 6 figures in `docs/img/`.
- `docs/eda.md`: the findings in plain English, 9 data biases with evidence and what we do, and text tables for every figure.
- EDA is not a DVC stage. It is run by hand. The 7-stage DAG stays as CLAUDE.md requires.

**Main findings**
1. Missing data is concentrated in 2015-2017 and in some cities. The 7 selected cities have no PM2.5 gaps in 2019-2020.
2. Strong yearly cycle in the north: Delhi is 5.5x higher in November than in August. South cities are flat and low.
3. **Part of the lockdown drop is just the season.** Comparing the same dates of 2019 gives a fair drop of 25-52%. The naive before and after comparison overstates it by 9-23 points in four cities.
4. The monitoring network grew (Delhi from 10 to 37 stations), so city averages are not fully comparable across years.
5. Extreme PM2.5 hours (250 or more) are rare outside Delhi, Lucknow and Kolkata, and almost absent in the lockdown period.

### How to run
```bash
source .venv/bin/activate
ruff check . && pytest -q                    # 60 tests (about 16 s)
dvc repro                                    # ingest + validate (validate about 32 s)
cat reports/validation.json | head -20       # the check report
python -m src.pipeline.eda                   # EDA CSVs (about 10 s)
python scripts/plot_eda.py                   # figures into docs/img/
python scripts/bench_pandas_ingest.py 3      # the pandas benchmark
```

### Measured numbers (full tables in `docs/metrics.md`)
| What | Value |
|------|-------|
| Validate time | 32.1 to 33.5 s over 4 runs, about 105,000 rows/s |
| Validate peak memory | about 3.4 GB with the 3 GB driver; about 1.4 GB with a 1 GB driver (same answer, 34.2 s) |
| Pandas vs Spark ingest | 3.4 to 3.9 s vs 8.0 to 8.4 s |
| EDA aggregates | about 9.4 s, 1,528 rows in 8 files |

### Things to know
- **A YAML trap:** an unquoted `NO:` in `params.yaml` is read as the boolean `false`, which crashed validate (`KeyError: 'NO'`). The keys are now quoted, and a test checks that every pollutant has a limit.
- **Memory:** the 3.4 GB peak is the JVM filling the heap it is allowed. It does not need that much, as the 1 GB test shows. I kept the 3 GB limit from CLAUDE.md. Free RAM on the VM is only about 3.9 GB, so run Spark stages alone.
- **Node.js is not installed,** so I could not run the palette validator script from the chart guidance. I used the first seven slots of its documented palette in the documented order, which is stated there to pass the adjacent-pair checks. I did not verify this myself. Everything is also given as text tables, so colour is never the only channel.
- **Drift will be partly seasonal.** Because of finding 3, the PSI drift signal in Stage 11 will react to the season as well as the lockdown. `docs/eda.md` says so. The design in `docs/HLD.md` is unchanged. Decide at Stage 11 whether to keep it as is or to add a seasonal reference.
- **City selection** (7 cities) was by long history and low missing share. Gurugram, Patna and Ahmedabad have more data than Kolkata or Jaipur but were left out because 15-35% of their PM2.5 is missing. This is listed as bias 1.
- **`docs/LLD.md`** was updated for the validate stage inputs and the EDA files.

### Five likely viva questions

**1. Why validate data in its own stage, and what stops the pipeline?**
So bad data cannot reach training silently. The stage computes 48 checks and splits them into hard failures (schema, duplicates, negative values, values above the sensor ceiling, missing ids, too little data in the selected cities) and warnings. Any hard failure stops the pipeline with a message like `PM2.5 > 1000 in 12 rows`, and the failure appears in `runs.jsonl` and later in the console. The report is still saved.

**2. Why split validate into Spark profiling and pure Python checks?**
Spark does what it is good at, counting over millions of rows in one pass. The decision logic is plain Python on a small dictionary, so it is fast to unit-test without starting Spark and easy to read. It also matches the functional style stated in the HLD.

**3. Pandas was faster than Spark in your benchmark. Why use Spark?**
On 283 MB that fits in memory, pandas is about 2x faster: Spark pays for JVM start and job planning. We use Spark because the course requires it as the data engine, and because it works on data larger than memory with the same code. We did not measure large data, so I would call that a design argument and not a result. The benchmark is honest about this.

**4. The lockdown caused a big drop in PM2.5. How sure are you of its size?**
Not as sure as the naive numbers suggest. Comparing before and after 25 March gives 30-75% drops, but April to June is naturally cleaner than January to March. Comparing the same dates of 2019 gives 25-52%. The effect is real in all 7 cities but smaller than it first looks, so drift alarms will partly be seasonal. We say this openly in `docs/eda.md`.

**5. What data biases did you find, and what did you do about them?**
Nine, listed in `docs/eda.md`. The main ones: missing data is concentrated in early years and some cities, so we do not make up values; the station network grew (Delhi 10 to 37), so city averages are not comparable across years, so we trust 2018 onwards most; extreme hours are rare outside the north, so the model will under-predict peaks and we report high-value error separately; and we only model 7 cities, so the app only offers those.
