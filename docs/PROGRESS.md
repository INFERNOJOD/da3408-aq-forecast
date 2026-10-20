# Progress Report: Stages 2, 3 and 4

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
