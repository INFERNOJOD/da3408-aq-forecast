# Test Report

I ran the whole suite and every acceptance check again on 2026-10-21, against the live serve stack, with the plan in `docs/test_plan.md`. The rollback drill found two real defects in the compose set-up. I fixed both and ran everything again. After the final audit (`docs/final_audit.md`) I added 9 tests and the checks E2E-18 to E2E-22, and on 2026-11-03 I ran the suite again (350 of 350). On 2026-11-05 I added 3 frontend tests for the forecast page's replay-clock note (353 of 353), then 5 tests for the rollback fix (D-2) and 1 for the console layout (D-5), and ran it once more. The pytest numbers below come from that last run; the other sections say when each check was run.

## 1. Summary

| | Count |
|---|---:|
| pytest test cases run | **359** |
| Passed | **359** |
| Failed | **0** |
| Errors | 0 |
| Skipped | 0 |
| End-to-end checks (E2E-01 to E2E-23) | **23 passed** |
| Acceptance criteria (AC-1 to AC-7) | **7 of 7 met** |
| Defects found | 5, all fixed (section 5) |

The pytest numbers are from `reports/ci/final/junit.xml` (`tests="359" failures="0" errors="0" skipped="0"`, 48.7 s), at commit `1341240` with the D-5 console fix in the workspace. The full CI output is in `reports/ci/final/last_run.log`. Earlier runs (350 of 350 at `e10bbaf`, 353 of 353 at `76de3f9`, 358 of 358 at `6e29d9e`) are in git history under the same path. The Stage 17 run (341 of 341 at `2c452c3`) is kept in `reports/ci/stage17/`. The warnings are deprecation and hint messages from MLflow, SQLAlchemy and Starlette, not from my code.

```
== summary (commit 1341240)
ruff           PASS     0s
ruff-format    PASS     0s
pytest         PASS    52s
dvc-status     PASS     0s
dvc-remote     PASS     1s
CI PASSED
```

## 2. pytest results by file

Each row lists the test cases from the plan that the file covers. The counts include parametrized cases, which is why `test_backend.py` has 97 results from 43 functions (`test_ops_requires_key` alone has 30).

| File | Plan cases | Run | Passed | Failed |
|------|-----------|----:|-------:|-------:|
| `test_common.py` | TC-01 | 10 | 10 | 0 |
| `test_stage_runner.py` | TC-02 | 9 | 9 | 0 |
| `test_ingest.py` | TC-03 | 8 | 8 | 0 |
| `test_bench_pandas.py` | TC-04 | 2 | 2 | 0 |
| `test_validate.py` | TC-05, TC-06 | 18 | 18 | 0 |
| `test_features.py` | TC-07 to TC-10 | 19 | 19 | 0 |
| `test_schema.py` | TC-11 | 4 | 4 | 0 |
| `test_eda.py`, `test_plot_eda.py` | TC-12 | 11 | 11 | 0 |
| `test_versioning.py` | TC-13 | 9 | 9 | 0 |
| `test_dvc_setup.py` | TC-14 | 6 | 6 | 0 |
| `test_modeling.py` | TC-15 to TC-18 | 12 | 12 | 0 |
| `test_train.py`, `test_train_plots.py` | TC-18, TC-19 | 10 | 10 | 0 |
| `test_aq_model.py` | TC-20 | 8 | 8 | 0 |
| `test_gate.py` | TC-21 | 6 | 6 | 0 |
| `test_registry.py` | TC-22 | 9 | 9 | 0 |
| `test_promotion_flow.py` | TC-23 | 6 | 6 | 0 |
| `test_rollback_script.py` | TC-24 | 3 | 3 | 0 |
| `test_model_server.py` | TC-25, TC-26 | 12 | 12 | 0 |
| `test_backend.py` | TC-27 to TC-35 | 97 | 97 | 0 |
| `test_drift.py` | TC-36 | 13 | 13 | 0 |
| `test_backend_drift.py` | TC-37 | 9 | 9 | 0 |
| `test_replay_script.py` | TC-38 | 5 | 5 | 0 |
| `test_ops_runner.py` | TC-39 | 22 | 22 | 0 |
| `test_frontend.py` | TC-40 to TC-44 | 25 | 25 | 0 |
| `test_monitoring.py`, `test_push_stage_metrics.py` | TC-45 | 9 | 9 | 0 |
| `test_security.py` | TC-46, TC-47 | 11 | 11 | 0 |
| `test_ci.py` | TC-48 | 6 | 6 | 0 |
| **Total** | 48 cases | **359** | **359** | **0** |

The slowest single tests are the Spark ones (`test_missing_by_city_year` 5.0 s, `test_validate_all_passes_on_good_data` 2.7 s, `test_validate_all_fails_on_impossible_value` 2.3 s). The suite took 48.7 s inside the 52 s pytest step.

## 3. End-to-end checks

"Today" means I ran it again for this report on 2026-10-21. The other rows were run in earlier stages, on the same machine. Their logs and numbers are in `docs/PROGRESS.md` and `docs/metrics.md`. I did not repeat those because they need the batch profile, which cannot run next to the serve stack, or because they change the served model.

| ID | Result | When | Evidence |
|----|--------|------|----------|
| E2E-01 Cold start | Pass | Stage 15 | page over HTTPS after 25 s, 9 of 9 targets up, 0 restarts (metrics.md, Stage 15) |
| E2E-02 Forecast latency | Pass | Today | section 4, AC-2 |
| E2E-03 Frontend → backend over TLS | Pass | Stage 15 | `BackendClient` in the frontend container read `https://backend:8000` with `/certs/ca.crt` (PROGRESS Part 15) |
| E2E-04 HTTPS for the browser | Pass | Stage 15 | `301 https://localhost/` from ports 80 and 8501; `curl` without the CA exits 60 (PROGRESS Part 15) |
| E2E-05 API key, live | Pass | Today | `/ops/rollback`: 401 with no key, 401 with `Bearer nope`, 200 with the key |
| E2E-06 Drift replay | Pass | Today | section 4, AC-3 |
| E2E-07 Drift → new model | Pass | Stage 11 | alert 17:20:09, request 17:20:13, `dvc repro` 17:20:22, v4 champion and smoke check 17:21:30; 2 min 47 s from drift to new model (metrics.md, Stage 11) |
| E2E-08 Alerts, live | Pass | Stage 14 | `PM25DriftHigh` made one retrain request; the three service alerts made none (metrics.md, Stage 14) |
| E2E-09 promtool | Pass | Stage 14 | `promtool test rules`: SUCCESS |
| E2E-10 Gate rejects a tie | Pass | Stage 16 | `reports/gate.json` (section 4, AC-4) |
| E2E-11 Rollback, live | Pass after fix | Today | section 4, AC-5; the first try failed (defect D-1) |
| E2E-12 Rollback with MLflow down | Pass after fix | Today | 400 after 5.0 s; aliases unchanged afterwards (defect D-2) |
| E2E-13 Hot swap | Pass | Stage 9 | 0 failed requests, both versions seen; run outside Docker (metrics.md, Stage 9) |
| E2E-14 CI with `--repro` | Pass | Stage 16 | every step PASS, `reports/ci/last_run.log` |
| E2E-15 Reproduce the champion | Pass | Today | section 4, AC-6 |
| E2E-16 Pre-commit hook | Pass | Stage 16 | commit refused with ruff D100 and F401; guard failed on `certs/ca.crt` and `.env` (PROGRESS Part 16) |
| E2E-17 Pages in a browser | Pass | 2026-11-05 | 11 screenshots in Firefox on the VM's desktop, in `docs/screenshots/` and linked from the user manual. Responsive: `05_forecast_mobile.png` uses Firefox's responsive mode at iPhone 14 size (393 x 852). The page fits the width, the text wraps and the two colour cards stack in one column. The first console screenshot `08_console_top.png` showed the replay time cut off (defect D-5). The retaken one shows it in full |
| E2E-18 Pushgateway survives a restart | Pass | 2026-10-27 | probe metric still served after `down`/`up` (metrics.md, "Final audit fixes") |
| E2E-19 Runner pauses containers | Pass | 2026-10-27 | frontend and Grafana stopped and started again within 2.3 s, request `failed` with `paused`, proxy 503 page (metrics.md) |
| E2E-20 Fresh clone | Pass | 2026-11-03 | `scripts/bootstrap.sh` exit 0 in 7 min 20 s, v1 champion, stack healthy in about 25 s, forecast 200, 9/9 targets up (metrics.md) |
| E2E-21 MLproject, fresh environment | Pass after fix | 2026-11-03 | the first run crashed (defect D-3); with `--experiment-name aq-pm25`: same MAE and byte-identical LightGBM files as the pipeline (metrics.md) |
| E2E-22 Failed run in the console | Pass | 2026-10-27, checked again 2026-11-03 | `demo-failure-20261027` failed in `validate` with "4 hard check(s) failed"; on 2026-11-03 `/pipeline/runs?limit=20`, the call the console makes, listed it as failed with that error |
| E2E-23 Pipeline in the batch container | Pass | 2026-11-05 | `container-20261105-214229`: all 7 stages succeeded in 74.4 s (ingest 7.7 s at 444,111 rows/s, validate 26.3 s, features 10.7 s, train 20.8 s), peak memory 2.39 GiB of the 2.5 GiB limit. Files owned by uid 1000, MLflow run `4c6ef2ee` in the host's `mlruns/`. The candidate tied v4 (6.467) and was rejected. Found D-4 first |

## 4. Acceptance criteria

### AC-1: the model beats persistence at both horizons: **met**

The champion is v4 (MLflow run `498b149f78e2418695c3bf7e01b91615`). Its evaluation window is 2020-03-30 20:00 to 2020-04-02 19:00, which is inside the lockdown. All models are scored on the same rows (497 at 1 h, 336 at 24 h).

| Model | MAE 1 h | MAE 24 h |
|-------|--------:|---------:|
| Persistence | 4.02 | 10.80 |
| Seasonal naive | 10.26 | 10.80 |
| Ridge | 4.27 | 10.55 |
| **LightGBM (served, v4)** | **3.54** | **9.39** |

v4 is 12% below persistence at 1 h and 13% below at 24 h. The first champion, v1, also met the criterion on its own window: 4.50 against 5.13 at 1 h and 13.54 against 14.70 at 24 h (run `0b70053677db487d8a4c5ff4763d4001`). The window is short, so a gap of a few percent would be within noise. These gaps are larger than that. Per city the model is not better everywhere: on v1's window it lost to the best baseline in Kolkata and Lucknow (metrics.md, Stage 7).

### AC-2: p95 forecast latency under 300 ms: **met**

300 serial `GET https://localhost:8000/forecast?city=...` calls on the live compose stack, rotating through the 7 cities, certificates checked against `certs/ca.crt`:

| Connection | p50 | p95 | p99 | max | Non-200 |
|------------|----:|----:|----:|----:|--------:|
| Reused | 9.5 ms | 13.5 ms | 20.5 ms | 380 ms | 0 |
| New TLS connection each time | 11.7 ms | 16.2 ms | 18.9 ms | 840 ms | 0 |

The p95 is about 20 times below the limit. Each run had one slow call (380 ms and 840 ms). I did not trace them. My guess is the backend's registry cache, which refreshes from MLflow every 30 s, but I have not checked it. They do not move the p95 or the p99.

### AC-3: drift fires on the lockdown and not on normal weeks: **met**

`python -m scripts.replay`, exit code 0, 2.4 s:

```
2016: drift    0 of 2185 h, 0 episodes, max cities 2, first None
2017: drift    0 of 2185 h, 0 episodes, max cities 2, first None
2018: drift    0 of 2185 h, 0 episodes, max cities 3, first None
2019: drift    0 of 2185 h, 0 episodes, max cities 3, first None
2020: drift  661 of 2185 h, 5 episodes, max cities 5, first 2020-03-31 23:00:00
acceptance: PASSED {'lockdown_triggers': True, 'normal_weeks_quiet': True, 'false_alarm_hours': 0, 'passed': True}
```

These match the committed `reports/drift_replay.json`. I want to be clear about one weakness. The rule needs 4 cities, and normal years reach 3, so the margin is one city. The thresholds and the city count were also chosen on the same 2016-2019 weeks, so "0 false alarms" is an in-sample result (HLD and PROGRESS Part 10).

### AC-4: the gate rejects a non-improving model: **met**

In the Stage 16 CI run, `dvc repro` retrained on the same data and cutoff as v4. Training is deterministic, so the candidate tied the champion exactly. `reports/gate.json`:

```
"passed": false,
"reasons": ["mean MAE 6.467 is not lower than champion v4 6.467 on the same window"],
```

`reports/register.json` has `"promoted": false, "version": null`. The registry still has v4 as champion (checked today), and the MLflow run `c9933e83…` is tagged `promotion=rejected` with the reason. A clearly worse candidate and a candidate above 1.02 times the best baseline are covered by `test_gate.py::test_candidate_must_beat_the_champion_strictly` and `test_both_reasons_are_reported`.

### AC-5: rollback restores the previous champion: **met, after fixing D-1**

The drill on the live stack, through the console's own endpoint:

| Time | Action | Result |
|------|--------|--------|
| 13:18:13 | `GET /forecast?city=Delhi` | version 4, 29.0 µg/m³, run `498b149f` |
| 13:18:13 | `POST /ops/rollback {}` | 200 `{"from_version":"4","to_version":"1"}` in 52 ms |
| 13:18:18 | `GET /forecast?city=Delhi` | version 1, 28.2 µg/m³, run `0b700536` (5 s after the rollback) |
| 13:18:18 | `POST /ops/rollback {}` (undo) | 200 `{"from_version":"1","to_version":"4"}` |
| 13:18:53 | `GET /forecast?city=Delhi` | version 4 again (35 s: the 30 s watcher poll plus about 4 s to load) |
| | `POST /ops/rollback {"version":"99"}` | 400 `Version 99 does not exist` |
| | `POST /ops/rollback {"version":"4"}` | 400 `Version 4 is already the champion` |

Afterwards the registry is as before: `champion` = 4, `previous` = 1. I polled once a second and only recorded the version once it changed, so this drill does not prove that no request failed during a swap; E2E-13 is the check for that.

### AC-6: reproducible from git commit + MLflow run ID: **met**

I started from the champion's run ID, as a reviewer would. The run `498b149f…` (v4) has the tags `git_commit=b2eff79`, `cutoff=2020-04-02 19:00:00`, `dvc_data_md5=7921cce1…dir` and `features_md5=2afa1813…`. It also has `git_dirty=true`, because the ops runner changed only the cutoff in `params.yaml`, and the cutoff is in the tags.

The Stage 16 CI run rebuilt the pipeline from a clean commit, `92537ef` (`git_dirty=false`), with the same cutoff. That gave run `c9933e83…`. Comparing the two:

| | v4 (`498b149f`) | Rebuild (`c9933e83`) |
|---|---|---|
| Raw data version | `7921cce1dbe07b5b8c33ffd85e4a34b4.dir` | same |
| Feature values hash | `2afa18138f64bab9472d0fa2c773f62d` | same |
| Mean MAE on the window | 6.467113514419853 | 6.467113514419853 |
| `h1.txt` (SHA-256, first 16) | `cc2493a351aaeda8` | same |
| `h24.txt` (SHA-256, first 16) | `4c03852a00892493` | same |

The two LightGBM files are identical byte for byte. So a model can be rebuilt from its run ID: the run gives the commit and the cutoff, `git checkout` and `dvc pull` give the code and data, and `dvc repro` gives the same model. The steps are in `README.md`, "Reproduce a result". One honest limit: the rebuild used a later commit than `b2eff79`. It was the same pipeline code apart from monitoring and CI changes, which is why the result is identical, but I did not check out `b2eff79` itself.

### AC-7: clean code and a passing suite: **met**

`scripts/ci.sh` (2026-11-05, at `1341240` plus the D-5 fix): ruff and format pass, 359 of 359 tests pass, `dvc status` says "Data and pipelines are up to date", and `dvc status -c` says "Cache and remote 'localremote' are in sync".

## 5. Defects found in this run

**D-1. The registry could not be written through the MLflow container.** My first `POST /ops/rollback` hung. The MLflow log showed `sqlite3.OperationalError: attempt to write a readonly database` and answered 503. The cause was the compose mount. I mounted `mlflow.db` as a single file, so Docker created its parent folder inside the container as `root:root`, and SQLite could not create its journal file next to the database. Reads worked, which is why forecasts, the console and the watcher never showed it. As far as I can tell from the history, the earlier writes (the v4 promotion, the Stage 8 rollback drill) all went straight to the SQLite file from host processes, never through the container, so nothing had exercised this path. **Fix:** compose now mounts the project folder into the `mlflow` container, so the folder is writable by my user. The cost is that the MLflow container can see the whole project, as the pipeline container already does.

**D-2. A rollback the caller gave up on was applied 4 minutes later.** I killed the hung `curl` from D-1, but the backend kept retrying the MLflow call with MLflow's default back-off. After I fixed D-1, that old request went through at 07:46:35 and moved `champion` from 4 to 1 while I was running the clean drill. That explains a confusing first attempt, where "already champion" seemed to pass. **Fix:** the backend now sets `MLFLOW_HTTP_REQUEST_MAX_RETRIES=2` and `MLFLOW_HTTP_REQUEST_TIMEOUT=10`. With MLflow stopped, a rollback now fails after 5.0 s, and the aliases did not change afterwards (E2E-12).

**Still weak after D-2, fixed on 2026-11-05.** With MLflow down, the rollback error said "No previous version to roll back to", because the lookup of `previous` swallowed the connection error and returned nothing. The answer was safe (nothing changed) but the message was wrong. **Fix:** the registry now treats only MLflow's "not found" codes (`RESOURCE_DOES_NOT_EXIST`, `INVALID_PARAMETER_VALUE`) as "not there". Any other error during a rollback raises `RegistryUnavailableError`, and the backend answers 503 `REGISTRY_UNAVAILABLE` (LLD section 1). Lookups for serving stay lenient, so forecasts keep working. Live check on the rebuilt backend, with the `mlflow` container stopped: `POST /ops/rollback` with `{}` gave 503 `REGISTRY_UNAVAILABLE` in 4.4 s, and with `{"version": "1"}` the same in 4.9 s. A forecast still answered 200 in 4.6 s. 35 s after MLflow was back, `champion` was still 4 and `previous` 1. The 4.5 s forecast with MLflow down is unchanged: the client still retries before it gives up.

**D-5. The console's replay time was cut off in a real browser** (2026-11-05, E2E-17). The first `08_console_top.png`, in Firefox at 90% zoom, showed the "Replay time" status box as "25 Mar, …". The final audit had marked this fixed, because Streamlit's `AppTest` showed the short value "25 Mar, 00:00". `AppTest` checks values, not widths. The four status boxes shared one row of the centred page, so each was about a quarter of its width. **Fix:** the console shows them as two rows of two. A new test, `test_console_status_boxes_are_two_per_row`, checks that each box sits in a half-width column. It fails on the old layout. On the rebuilt frontend, the live console has all four boxes at half width, with "Replay time" at "25 Mar, 00:00". **Verified and closed (2026-11-05, 22:37):** the retaken `08_console_top.png`, in Firefox at default zoom, shows the two rows of two, and "Replay time" reads "25 Mar, 00:00" in full.

**D-4. The batch container could not run the pipeline** (2026-11-05, E2E-23). Compose runs it as my host uid (1000), so the files it writes stay mine. The image only knows its own user (10001). DVC failed at once with `getpwuid(): uid not found: 1000` (from `getpass.getuser()`). With `USER` set, Spark failed next, in Hadoop's login: `invalid null input: name`. That code reads the user database directly and ignores the variable. **Fix:** compose mounts the host's `/etc/passwd` and `/etc/group` read-only into the pipeline container. The container already runs as my uid and mounts the whole project, so this adds little exposure, and the published image did not need a rebuild. Checked through plain `docker compose run`: `id -un` gives my user, `dvc status` works and a Spark session starts as `krish-yadav`. The Spark attempt left one real `ingest failed` record (`container-20261105-214205`) in `runs.jsonl`.

**D-3. `mlflow run` crashed when it logged the run** (2026-11-03, E2E-21). It trained both horizons and then failed with "Cannot start run with ID ... because active experiment ID does not match environment run ID". `mlflow run` creates its run in the Default experiment, and `train.py` sets the experiment `aq-pm25`. On 2026-10-27 the fresh-environment run never got as far as training, so this was the first time I saw the error. **Fix:** the documented command is now `mlflow run . -e main --env-manager uv --experiment-name aq-pm25` (README, test plan). With it the run succeeds. I did not change `train.py`: the pipeline and the MLproject run should log to the same experiment.

## 6. What this report does not show

- **One browser, no real phone.** The pages were checked in Firefox on the VM, and the narrow layout in Firefox's responsive mode at iPhone 14 size (E2E-17). Not on a real phone or in another browser.
- **Auto-rollback after a failed smoke check** is tested with fakes only (`test_failed_smoke_check_rolls_back`). I have not made a real model fail.
- **The hot swap** with 0 failed requests was measured outside Docker (Stage 9), not in the compose stack.
- **Latency is serial.** I did not load-test with concurrent users.
- **`PipelineStageFailed` and `ForecastErrorHigh`** are tested with promtool only, not fired live.
