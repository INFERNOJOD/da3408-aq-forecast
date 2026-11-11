# Commit map

History was rewritten on 2026-11-11 to clean up commit messages; code is unchanged. Hashes in MLflow tags and evidence images map through this table.

The same goes for `reports/register.json` and `reports/train_metrics.json`. They are DVC pipeline outputs, so they keep the commit hash they were produced with, like the MLflow tags. Hashes quoted in the other docs, reports and evidence transcripts were updated to the new values.

| Old | New | Subject |
|---|---|---|
| `0494f85` | `0d7a068` | Rubric checklist: items 2 and 3 no longer contradict themselves |
| `32dbf7f` | `156152c` | Final audit: doc claims matched to code and screenshots, CI log |
| `141fb4b` | `038a8ff` | Forced run times in metrics.md, browser notes corrected |
| `e8e8b1a` | `acafadc` | Console screenshots retaken after the 7-stage run, evidence captions, CI log |
| `f0c275b` | `3e7f123` | Forced full pipeline run manual-20261111-042650: 7/7 stages, gate kept v4 |
| `34b5051` | `eee829b` | Console tables show "–", architecture diagram parses, evidence at 371 tests |
| `acd9531` | `082a01c` | D-6 gauge fix, evidence gallery curated to 79 images, secret check |
| `cc39d92` | `547ca62` | Evidence gallery: 222 captures per rubric line, capture scripts, live drift story |
| `aeb8f83` | `6c65eef` | Screenshots 10 and 11 retaken on the new console |
| `65c14cf` | `6448191` | First person in HLD, PLAN and PROGRESS where the docs spoke to someone else |
| `3744bcd` | `cb10b74` | Pre-submission fixes: console messages, stale doc lines, README section |
| `5092d56` | `7ce97cd` | Screenshot 08 retaken, D-5 verified and closed |
| `a580bd2` | `5ae364f` | Screenshots in the user manual, E2E-17 passed, console status boxes two per row |
| `1341240` | `cf5bff1` | Pipeline runs in the batch container (E2E-23); fix for unknown host uid (D-4) |
| `6e29d9e` | `3dd6081` | Rollback with MLflow down: 503 REGISTRY_UNAVAILABLE, not "No previous version" |
| `fbd8039` | `30b62f9` | aq-mlflow on Docker Hub: all five images multi-arch, Docker Hub PASS |
| `16f7262` | `e3666ba` | Multi-arch images on Docker Hub: frontend, backend, model-server, pipeline |
| `0d01868` | `0bdc3a8` | Pipeline run manual-20261105-174821: all 7 stages, candidate rejected |
| `4b01925` | `4256eb5` | Test count 353 of 353 in every doc that quotes it |
| `76de3f9` | `6f3bb7c` | User manual: image links for the screenshots, written steps for the certificate |
| `dc684a3` | `2a0444b` | Forecast page says whether the demo clock is paused or running |
| `a9610f2` | `2f2e95e` | Final CI run after the re-audit: 350 of 350, DVC clean and in sync |
| `c8201f8` | `2a9bbd4` | Re-audit after the final-audit fixes |
| `e10bbaf` | `5785004` | MLproject tested in a fresh uv environment (E2E-21) |
| `0a81f6e` | `05a7b61` | Real pipeline run: dvc repro -f, all 7 stages (audit fix a10) |
| `e0a7cb1` | `d7e0b03` | Bootstrap script for a fresh clone, tested in a clean clone (audit fix a2) |
| `c27e809` | `99b842e` | Record where the final-audit fixes stand before the pause |
| `3484879` | `d30d9ab` | User manual: starting the app takes two commands, not one |
| `efb8883` | `7dae2c9` | Test plan: list the tests added by the final audit fixes |
| `3400783` | `ed87793` | Docs: fix the architecture diagram and the other audit inconsistencies |
| `fd7d292` | `e2046a6` | LLD: list every pipeline trigger value (ci, initial) |
| `e10f521` | `5ccdd24` | Console: short replay time in the status box, failed runs table |
| `56779b3` | `a66701c` | OpenAPI spec documents the LLD error body and status codes |
| `69e9b4e` | `957dea2` | Document how to start the ops runner and what happens without it |
| `4841b2e` | `1c95beb` | Ops runner stops the frontend and Grafana around the batch |
| `cc0822a` | `ba0473a` | Fix Pushgateway persistence: mount the volume on /pushgateway |
| `5ebddab` | `24cb679` | Final audit: rubric PASS/WEAK/FAIL table, inconsistencies, what's left |
| `1cdba84` | `d8e4ab5` | Stage 17: test plan, test report (341/341 passed, 7/7 acceptance criteria met), user manual, README, rubric checklist |
| `2c452c3` | `df2dab9` | Stage 16 results: CI run log and JUnit XML, dvc.lock from the CI repro (candidate tied v4, rejected), outputs pushed to the DVC remote, PLAN, PROGRESS, metrics |
| `92537ef` | `f8fde15` | Stage 16 code: scripts/ci.sh (ruff, pytest, dvc repro/push/status), local pre-commit hooks, tests |
| `4d39d3a` | `d2a3cf9` | Frontend: hide Streamlit's Deploy button and top-right menu (client.toolbarMode = minimal) |
| `a1735df` | `196d653` | Stage 15: TLS with a local CA, Caddy HTTPS proxy for the frontend, HTTPS backend, key only in .env, non-root checks |
| `a27e7ed` | `1869cad` | Stage 14: Prometheus scrapes all components, alert rules with promtool tests, provisioned Grafana dashboards, MLflow exporter, frontend exporter at boot, PLAN and PROGRESS |
| `0e2c1f9` | `fc2365a` | Frontend /forecast and /console paths, 2020 demo note, health-gated compose start order |
| `3e1c280` | `4107806` | Stage 13: serve stack runs in compose and is healthy, pipeline image builds, MLflow memory fix, metrics and PROGRESS |
| `a038288` | `4e55169` | Docs: frontend and backend images build on arm64; stack not yet run |
| `1147f46` | `242e07d` | Stage 13 (partial): Dockerfiles for frontend, backend and pipeline, compose with serve/batch profiles and mem_limit, multi-arch script, PLAN and PROGRESS |
| `d5f38cf` | `d843bba` | Stage 12: Streamlit frontend (Forecast page, Pipeline console), REST client, UI metrics, tests, LLD/HLD |
| `9e2273a` | `474db67` | One retrain per drift episode: episode gate, drift.episode_clear_hours, test, HLD/LLD |
| `e7e7433` | `a3a194a` | Stage 11 results and docs: drift-triggered retrain promoted v4, acceptance replay passed, HLD/LLD/PLAN/PROGRESS/metrics updated |
| `b2eff79` | `b130997` | Stage 11 code: PSI drift module, thresholds in features stage, live drift report, ops runner with smoke check and auto-rollback, replay acceptance script, drift alert config, tests |
| `a19cd16` | `3515b41` | Stage 10: FastAPI backend (forecast, pipeline, ops endpoints, metrics), tests, LLD and docs |
| `9adf52b` | `bcafb96` | Stage 9: model server (mlflow models serve, metrics proxy, champion watcher), Dockerfile, tests, docs |
| `2c32708` | `39461ce` | Stage 8 results: dvc.lock and reports from a clean-tree run (candidate rejected, champion v1) |
| `a4733d8` | `695f7c9` | Stage 8 docs: HLD, LLD, plan, metrics and progress report |
| `feab67a` | `748c0f8` | Stage 8 code: evaluate, test and register stages, registry client, rollback script, Ridge-or-LightGBM package |
| `29adeae` | `3b0f232` | Apply decisions: drift rule, 90-day half-life, per-horizon promotion |
| `5e24470` | `d72352b` | Recency half-life 30 -> 90 days |
| `10ffcb8` | `0affe87` | Stage 7 results: train metrics, dvc.lock, plan status and progress report |
| `865e661` | `645bbbd` | git_dirty ignores files the pipeline rewrites (dvc.lock, reports/) |
| `410a0cc` | `eeec08e` | Use a hash of the feature values as the data version tag |
| `b0dbca6` | `ebb05a9` | Stage 7: train stage (Ridge, LightGBM, baselines) with MLflow logging; same-season drift reference |
| `6ead646` | `ee0eb48` | Correct claim about missing hourly rows in progress report and metrics |
| `2044b11` | `962ae25` | Update plan status and progress report for Stage 6 |
| `cea9532` | `4fa51a0` | Stage 6: Spark features stage (lags, rolling, calendar, targets) with drift baseline |
| `91eda26` | `aaf3a13` | Lower Spark driver memory from 3g to 2g |
| `3c3fb6f` | `f3b3932` | Rewrite HLD, architecture, EDA and progress docs in the first-person writing voice |
| `171be01` | `80377d2` | Update plan status and progress report for stages 5 and 5b |
| `ed7b6bd` | `fc9f797` | Stage 5b: EDA with Spark aggregates, 6 figures, documented data biases |
| `040e474` | `c82c9e0` | Stage 5: Spark validate stage (48 data checks) with validation report |
| `d5b11f2` | `a200228` | Remove empty dirs, track stage status in PLAN, add pandas vs Spark ingest benchmark |
| `0a9a6a6` | `54bfde3` | Add progress report for stages 2-4 |
| `2491249` | `d3228c4` | Stage 4: Spark ingest stage (CSV to Parquet) with run records and metrics |
| `1de6eed` | `9025b49` | Stage 3: DVC with local remote, data/raw tracked and pushed |
| `6f8ca82` | `1022dee` | Stage 2: project skeleton, tooling, shared config/logging/errors |
| `36e98ec` | `fec94b5` | Stage 1: architecture diagram, HLD and LLD design documents |
| `6b50365` | `fc771b2` | Allow Docker Hub for image publishing only |
| `ed76c08` | `3cbeeeb` | Add official rubric and align build plan with every rubric line |
| `1c7e4c7` | `ea15071` | Stage 0: project brief, build plan, raw data profile, gitignore |
