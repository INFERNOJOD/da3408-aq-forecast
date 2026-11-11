# Evidence Gallery

This folder holds screenshots and terminal captures for every line of the rubric and the guidelines (`docs/rubric.md`). I captured them on 2026-11-10 on the project VM, at commit `aeb8f83`, with the serve stack running. Each PNG has a dark strip on top with the time, the URL or command, and one line saying what it proves. A terminal capture is also kept as a `.txt` next to its PNG, with the exact command on its `$` line.

The first capture run made 222 images. I kept the one or two clearest per rubric line and deleted the rest (other cities, every Swagger endpoint, single Grafana panels already visible on a full dashboard, retakes and terminal outputs that repeated another file), so this set has 79 images and 27 transcripts.

**Retaken on 2026-11-11.** Three images showed an old test count, so I retook them on the host with the Pillow renderer (`python scripts/capture_evidence.py terminal-pil --only <path>`), at `acd9531` with the console table change in the workspace: `05_testing/03` (now a transcript of the report's summary section, not the rendered page), `05_testing/05` and `07_source_control_ci/03`. All three show 371 of 371.

**Two console captures taken by hand on 2026-11-11.** After a forced full pipeline run (`manual-20261111-042650`, all 7 stages green) and the frontend rebuild that shows "–" instead of `None` in the tables, I took `02_pipeline_viz/01_console_top` and `02_pipeline_viz/02_runs_and_failures` myself in Firefox at 13:36. They are the same files as `docs/screenshots/08_console_top.png` and `09_console_runs.png`, so they have no dark caption strip. The browser bar shows the URL and the desktop clock shows the time.

**How it was made.** `docs/evidence/` was captured automatically by `scripts/capture_evidence.py` (Playwright in Docker, image `mcr.microsoft.com/playwright/python:v1.49.1-noble`, arm64), written by Claude Code under my direction. `scripts/capture_evidence_host.sh` runs the terminal commands on the host and drives the live story. Run again, the scripts make the full uncurated set under the original file names. The 11 user-manual screenshots in `docs/screenshots/` were taken by me by hand in Firefox on the VM. Firefox is installed there, but it is a snap and hangs in headless mode, so it could not be scripted; that is why the automated captures run Playwright's Chromium in Docker. The Playwright image was removed afterwards.

**The API key** is not in any image or text file. The script types it into the console's masked field (dots only), checks the visible text of every page before saving the screenshot, and stops if the key is there. Commands that use the key show the literal text `$OPS_API_KEY`. The final set was checked again, by text search and by looking at every image with a key field, an ops section or a terminal.

| Section | PNG | TXT |
|---|---:|---:|
| 01_ui | 7 | 0 |
| 02_pipeline_viz | 6 | 0 |
| 03_design | 9 | 1 |
| 04_implementation | 5 | 2 |
| 05_testing | 5 | 2 |
| 06_data_engineering | 5 | 2 |
| 07_source_control_ci | 5 | 4 |
| 08_experiment_tracking | 6 | 1 |
| 09_monitoring | 7 | 2 |
| 10_packaging | 7 | 4 |
| 11_guidelines | 17 | 9 |
| **Total** | **79** | **27** |

## The live story (11_guidelines/05 to 12)

This was the only part that changed state. With the ops runner started, I reset and started the replay from the console. Drift switched on 166 s later (05). `PM25DriftHigh` went pending (06), then firing (07). Alertmanager called the backend webhook, which wrote a retrain request with cutoff 2020-04-04 04:00 (08). The runner paused the frontend and Grafana, ran `dvc repro` with the new cutoff (09: features and train in Spark, with times and rows/sec) and started them again 41 s later. **The gate rejected the new model** (10): its mean MAE was 6.007 and champion v4's was 5.948 on the same window, so nothing was registered and v4 kept serving. Then I rolled back to v1 from the console (11) and back to v4 (12). The captions still carry the step numbers of the full sequence. The step times are in `docs/metrics.md`, "Evidence run: drift to retrain, live".

Afterwards I put everything back: v4 champion and v1 previous, the replay stopped at 25 Mar 2020, `params.yaml`, `dvc.lock` and `reports/` from git, the DVC outputs from the cache (`dvc status` clean), today's request file and `ops/episode.json` removed, and the runner stopped. What stays, on purpose, is the history: the rejected run `b010fbb6` in MLflow, its rows in `reports/runs.jsonl` (so the console's last run is now the drift run), and the runner's log `ops/logs/rt-20261110-144028.log`.

## Rubric line to evidence

Paths are relative to this folder.

### Demonstration: Web App Front-end UI/UX [3]

| Rubric line | Evidence | Caption |
|---|---|---|
| Intuitive for the problem | [01_ui/01_forecast_delhi.png](01_ui/01_forecast_delhi.png), [01_ui/02_forecast_kolkata.png](01_ui/02_forecast_kolkata.png) | The forecast page: 1 h and 24 h PM2.5 cards in the CPCB colour, the category and the health advice |
| Easy for non-technical users | [01_ui/01_forecast_delhi.png](01_ui/01_forecast_delhi.png), [01_ui/07_user_manual.png](01_ui/07_user_manual.png) | Plain sentences, units on every number, a note that the dates are a 2020 replay |
| Foolproof | [01_ui/04_unknown_city_typed.png](01_ui/04_unknown_city_typed.png), [02_pipeline_viz/03_wrong_key.png](02_pipeline_viz/03_wrong_key.png), [04_implementation/04_error_body_live.txt](04_implementation/04_error_body_live.txt) | Typing "Pune" finds no option; a wrong key shows no buttons; bad input at the API gives 404/422/405 in one error shape. `03_wrong_key` was taken before the 2026-11-11 table fix, so its run table still shows "None" in empty cells |
| Free of UI errors | [01_ui/06_backend_down_message.png](01_ui/06_backend_down_message.png) | Backend down: one plain sentence, no stack trace (a second frontend pointed at a dead `BACKEND_URL`) |
| Good colours, shapes, look-and-feel | [01_ui/03_colour_legend.png](01_ui/03_colour_legend.png), [01_ui/02_forecast_kolkata.png](01_ui/02_forecast_kolkata.png) | The six CPCB categories and colours, rounded cards with readable text on each colour |
| Responsive | [01_ui/05_mobile_393px.png](01_ui/05_mobile_393px.png) | Phone width 393 x 852 (Chromium mobile emulation): the cards stack, nothing is cut off |
| User manual exists | [01_ui/07_user_manual.png](01_ui/07_user_manual.png) | `docs/user_manual.md` rendered with its 11 hand-taken screenshots, on 2026-11-10. Screenshots 08 and 09 in this render are the older console captures (with "None" in empty cells); the manual now embeds the ones retaken on 2026-11-11 |

### Demonstration: ML Pipeline Visualization [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| Separate UI screen for the pipeline incl. ingestion and engineering | [02_pipeline_viz/01_console_top.png](02_pipeline_viz/01_console_top.png) | `/console`: status boxes (backend ok, model server up, champion 4), the 7-stage DVC DAG coloured by status with all 7 green for `manual-20261111-042650`, the stage table |
| MLOps tool UIs | [02_pipeline_viz/06_grafana_pipeline.png](02_pipeline_viz/06_grafana_pipeline.png), [08_experiment_tracking/01_runs.png](08_experiment_tracking/01_runs.png) | Grafana "AQ pipeline" over 7 days and MLflow, both linked from the console |
| Pipeline management console | [02_pipeline_viz/05_ops_section.png](02_pipeline_viz/05_ops_section.png), [02_pipeline_viz/04_drift_with_key.png](02_pipeline_viz/04_drift_with_key.png) | Replay start/stop/reset, retrain and rollback buttons and live drift, behind the masked key |
| Console of errors, failures and successful runs | [02_pipeline_viz/02_runs_and_failures.png](02_pipeline_viz/02_runs_and_failures.png) | Success and failure counts (18 and 2 of the last 20), the two failed runs with stage and error, the run table with `manual-20261111-042650` on top, and the registry with v4 champion and v1 previous |
| Pipeline speed and throughput | [02_pipeline_viz/01_console_top.png](02_pipeline_viz/01_console_top.png), [02_pipeline_viz/06_grafana_pipeline.png](02_pipeline_viz/06_grafana_pipeline.png) | Duration, rows out and rows/sec per stage (ingest 11.9 s at 289,706 rows/s), and over time in Grafana |

### Software Engineering: Design Principle [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| Design document | [03_design/02_hld.png](03_design/02_hld.png) | `docs/HLD.md` rendered: design choices with reasons |
| OO or functional paradigm stated | [03_design/02_hld.png](03_design/02_hld.png) (section 3, "Programming paradigm") | Functional pipeline stages, object-oriented services |
| LLD with API endpoints and I/O specs | [03_design/04_lld.png](03_design/04_lld.png) | `docs/LLD.md` rendered: every endpoint, its input, output, status codes and the error body |
| Architecture diagram | [03_design/01_architecture.png](03_design/01_architecture.png) | `docs/architecture.md` with one paragraph per block. The diagram in this capture is Mermaid's "Syntax error in text", to be retaken from GitHub after push: see "What I could not capture" |
| HLD diagram | [03_design/03_hld_diagram.png](03_design/03_hld_diagram.png) | The lifecycle diagram |
| Loose coupling via configurable REST | [03_design/09_frontend_never_imports_backend.png](03_design/09_frontend_never_imports_backend.png), [01_ui/06_backend_down_message.png](01_ui/06_backend_down_message.png) | No frontend module imports backend code, the URL comes from `BACKEND_URL`, and the same image ran against another URL |
| API endpoints as designed | [03_design/05_fastapi_docs.png](03_design/05_fastapi_docs.png), [03_design/06_endpoint_get_forecast.png](03_design/06_endpoint_get_forecast.png), [03_design/07_endpoint_post_ops_rollback.png](03_design/07_endpoint_post_ops_rollback.png), [03_design/08_lld_vs_openapi.png](03_design/08_lld_vs_openapi.png) | Swagger UI, two key endpoints expanded, and the LLD's 14 endpoints next to the live `/openapi.json`: all match |

### Software Engineering: Implementation [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| Standard Python coding style | [04_implementation/01_ruff.png](04_implementation/01_ruff.png) | `ruff check` and `ruff format --check` pass, and the rule set |
| Logging | [04_implementation/02_common_logging_setup.png](04_implementation/02_common_logging_setup.png) | One logging setup used by every module |
| Comprehensive exception handling | [04_implementation/03_backend_errors.png](04_implementation/03_backend_errors.png), [04_implementation/04_error_body_live.png](04_implementation/04_error_body_live.png) | Handlers that give the LLD error body; live 404, 422, 404, 405 |
| Inline comments and docstrings | [04_implementation/05_backend_app.png](04_implementation/05_backend_app.png), [04_implementation/03_backend_errors.png](04_implementation/03_backend_errors.png) | Docstrings on every function, comments where a choice needs a reason |
| Design document adhered to / APIs follow the spec | [03_design/08_lld_vs_openapi.png](03_design/08_lld_vs_openapi.png) | Every LLD endpoint is live and every live endpoint is in the LLD |
| API-key check | [04_implementation/05_backend_app.png](04_implementation/05_backend_app.png) | `require_key`: Bearer token, `hmac.compare_digest`, 401 otherwise |
| Unit tests implemented | [05_testing/05_pytest_full.png](05_testing/05_pytest_full.png) | The whole suite passes: 371 passed (2026-11-11) |

### Software Engineering: Testing [1]

| Rubric line | Evidence | Caption |
|---|---|---|
| Test plan | [05_testing/01_test_plan.png](05_testing/01_test_plan.png) | `docs/test_plan.md`: scope, levels, environment, how to run, acceptance criteria |
| List of test cases | [05_testing/02_test_case_list.png](05_testing/02_test_case_list.png) | TC-01 to TC-49 and E2E-01 to E2E-23 |
| Test report with passed and failed counts | [05_testing/03_test_report_summary.png](05_testing/03_test_report_summary.png), [05_testing/05_pytest_full.png](05_testing/05_pytest_full.png) | Cases run, passed and failed: 371 run, 371 passed, 0 failed (the summary section of `docs/test_report.md` and the pytest run, both 2026-11-11) |
| Acceptance criteria defined and met | [05_testing/01_test_plan.png](05_testing/01_test_plan.png) (section 5), [05_testing/04_acceptance_criteria_met.png](05_testing/04_acceptance_criteria_met.png) | AC-1 to AC-7 defined in the plan, each met in the report. This page was rendered on 2026-11-10, so its AC-7 paragraph still ends at the 362-test run; the report now adds the 367 and 371 runs |

### AIOps: Data Engineering [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| Ingestion/transformation pipeline with Spark | [06_data_engineering/01_spark.png](06_data_engineering/01_spark.png), [06_data_engineering/02_spark_repro_log.png](06_data_engineering/02_spark_repro_log.png) | Spark local mode, 2g driver, 8 shuffle partitions; the Spark output of a full `dvc repro` |
| Throughput and speed | [06_data_engineering/03_throughput_history.png](06_data_engineering/03_throughput_history.png), [06_data_engineering/04_metrics_ingest.png](06_data_engineering/04_metrics_ingest.png), [11_guidelines/09_story_pipeline_log.png](11_guidelines/09_story_pipeline_log.png) | Seconds and rows/sec of every stage run since October; CSV 283 MB to Parquet 65 MB; today's live features run at 27,607 rows/s |
| Spark vs pandas benchmark | [06_data_engineering/05_spark_vs_pandas.png](06_data_engineering/05_spark_vs_pandas.png) | pandas was about twice as fast on this small data |

### AIOps: Source Control & CI [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| CI implemented using DVC | [07_source_control_ci/03_ci_run.png](07_source_control_ci/03_ci_run.png) | A full passing `scripts/ci.sh` run on 2026-11-11: ruff, format, pytest (371 passed), `dvc status`, `dvc status -c` |
| DVC DAG representing the CI pipeline | [07_source_control_ci/01_dvc_dag.png](07_source_control_ci/01_dvc_dag.png), [07_source_control_ci/02_dvc_yaml.png](07_source_control_ci/02_dvc_yaml.png) | `dvc dag` and `dvc.yaml`: the 7 stages with deps, params and outputs |
| Git and DVC for source, data and model versioning | [07_source_control_ci/04_git_log.png](07_source_control_ci/04_git_log.png), [07_source_control_ci/05_data_versioned_by_dvc.png](07_source_control_ci/05_data_versioned_by_dvc.png) | Git history; the data only as a `.dvc` pointer; data and model hashes in `dvc.lock` |

### AIOps: Experiment Tracking [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| Tracking while models are built | [08_experiment_tracking/01_runs.png](08_experiment_tracking/01_runs.png) | Every training run in the `aq-pm25` experiment |
| Metrics, parameters and artifacts | [08_experiment_tracking/02_champion_run_overview.png](08_experiment_tracking/02_champion_run_overview.png), [08_experiment_tracking/04_artifact_feature_importance.png](08_experiment_tracking/04_artifact_feature_importance.png) | 94 metrics, 24 parameters, tags, and the logged feature importance plot |
| Provisions beyond autolog | [08_experiment_tracking/05_champion_run_tags.png](08_experiment_tracking/05_champion_run_tags.png), [08_experiment_tracking/03_champion_run_metrics.png](08_experiment_tracking/03_champion_run_metrics.png) | Tags `git_commit`, `git_dirty`, `dvc_data_md5`, `features_md5`, `cutoff`, `trigger`, `promotion`; MAE per city and horizon |
| Model registry | [08_experiment_tracking/06_registry_versions.png](08_experiment_tracking/06_registry_versions.png) | Versions 1 and 4 with the `previous` and `champion` aliases |

### AIOps: Exporter Instrumentation & Visualization [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| Prometheus instrumentation | [09_monitoring/06_backend_metrics.png](09_monitoring/06_backend_metrics.png), [09_monitoring/07_model_server_metrics.png](09_monitoring/07_model_server_metrics.png) | `/metrics` of the backend and of the model server |
| All components monitored | [09_monitoring/01_prometheus_targets.png](09_monitoring/01_prometheus_targets.png), [09_monitoring/03_retention_scrape.png](09_monitoring/03_retention_scrape.png) | 9 scrape jobs (backend, model server, frontend, Pushgateway for the pipeline, MLflow, node, Prometheus, Alertmanager, Grafana), all up; every 15 s, 2 days retention |
| Information points and alerting | [09_monitoring/02_prometheus_rules.png](09_monitoring/02_prometheus_rules.png), [09_monitoring/04_alertmanager_status.png](09_monitoring/04_alertmanager_status.png) | Drift, error-ratio, 5xx-rate, model-server, target-down and failed-stage rules; Alertmanager routes to the backend webhook |
| Grafana in near real time | [09_monitoring/05_grafana_aq_service.png](09_monitoring/05_grafana_aq_service.png), [02_pipeline_viz/06_grafana_pipeline.png](02_pipeline_viz/06_grafana_pipeline.png) | Both dashboards, provisioned from JSON, refreshing every 15 s |

### AIOps: Software Packaging [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| MLflow for APIfication of the model | [10_packaging/06_model_serving.png](10_packaging/06_model_serving.png) | `mlflow models serve` answers `/ping` and `/invocations` with predictions and the version |
| MLproject for identical environments | [10_packaging/01_mlproject_entry_points.png](10_packaging/01_mlproject_entry_points.png) | `MLproject` and `python_env.yaml`: entry points and the pinned environment, the same versions as `uv.lock` |
| FastAPI for the APIs the UI needs | [10_packaging/07_backend_forecast.png](10_packaging/07_backend_forecast.png), [03_design/05_fastapi_docs.png](03_design/05_fastapi_docs.png) | `/forecast` with the model version, run ID and commit |
| Backend and frontend dockerized | [10_packaging/03_dockerfile_frontend.png](10_packaging/03_dockerfile_frontend.png), [10_packaging/04_dockerfile_backend.png](10_packaging/04_dockerfile_backend.png) | One Dockerfile per service |
| docker compose with two separate services | [10_packaging/02_docker_compose.png](10_packaging/02_docker_compose.png), [10_packaging/05_compose_ps.png](10_packaging/05_compose_ps.png) | frontend and backend as separate services with `mem_limit`; all 10 containers up, and the four with a health check (mlflow, model server, backend, frontend) healthy |
| Multi-arch images | [11_guidelines/17_dockerhub_api.png](11_guidelines/17_dockerhub_api.png) | All 5 images with linux/amd64 and linux/arm64 |

### Mandatory documents

| Document | Evidence |
|---|---|
| Architecture diagram with block explanations | [03_design/01_architecture.png](03_design/01_architecture.png) |
| HLD with design choices and rationale | [03_design/02_hld.png](03_design/02_hld.png) |
| LLD with endpoint definitions and I/O specs | [03_design/04_lld.png](03_design/04_lld.png) |
| Test plan and test cases | [05_testing/01_test_plan.png](05_testing/01_test_plan.png), [05_testing/02_test_case_list.png](05_testing/02_test_case_list.png) |
| User manual for non-technical users | [01_ui/07_user_manual.png](01_ui/07_user_manual.png) |

### Guidelines

| Guideline | Evidence | Caption |
|---|---|---|
| Reproducible via git commit + MLflow run ID | [11_guidelines/01_reproducibility_tags.png](11_guidelines/01_reproducibility_tags.png), [11_guidelines/02_ac6_reproducible.png](11_guidelines/02_ac6_reproducible.png) | A forecast names its version, run and commit; the run's tags lead to code and data; a rebuild gave the same hashes, MAE and model bytes |
| EDA and documented data biases | [11_guidelines/03_eda.png](11_guidelines/03_eda.png), [11_guidelines/04_data_biases.png](11_guidelines/04_data_biases.png) | EDA with its six figures; nine biases and what I do about each |
| Automated monitoring and alerting | [11_guidelines/05_story_drift_yes.png](11_guidelines/05_story_drift_yes.png), [11_guidelines/06_story_alert_pending.png](11_guidelines/06_story_alert_pending.png), [11_guidelines/07_story_alert_firing.png](11_guidelines/07_story_alert_firing.png) | Drift YES (4 cities needed, 4 above), `PM25DriftHigh` pending, then firing |
| Automated retraining | [11_guidelines/08_story_retrain_request.png](11_guidelines/08_story_retrain_request.png), [11_guidelines/09_story_pipeline_log.png](11_guidelines/09_story_pipeline_log.png), [11_guidelines/10_story_gate_decision.png](11_guidelines/10_story_gate_decision.png), [08_experiment_tracking/05_champion_run_tags.png](08_experiment_tracking/05_champion_run_tags.png) | The webhook's request, `dvc repro` with the new cutoff, the gate's decision (rejected, v4 stays); v4 itself was promoted by the same loop in October (`trigger = drift_alert`, `promotion = promoted`) |
| Rollback for failed deployments | [11_guidelines/11_story_rollback_to_v1.png](11_guidelines/11_story_rollback_to_v1.png), [11_guidelines/12_story_rollback_to_v4.png](11_guidelines/12_story_rollback_to_v4.png) | "Rolled back from version 4 to version 1.", then back to version 4 |
| Encryption and security | [11_guidelines/13_tls_certificate.png](11_guidelines/13_tls_certificate.png), [11_guidelines/14_ops_auth.png](11_guidelines/14_ops_auth.png), [11_guidelines/15_secrets_not_in_git.png](11_guidelines/15_secrets_not_in_git.png) | Both certificates verify against my CA (`Verify return code: 0`); 401 without or with a wrong key, 200 with it; `.env` and keys ignored, the key in no commit |
| Docker Hub | [11_guidelines/17_dockerhub_api.png](11_guidelines/17_dockerhub_api.png) | Docker Hub's API: `latest` and `0.1.0` of all 5 images, each linux/amd64 and linux/arm64 |
| No cloud platforms | [11_guidelines/16_no_cloud.png](11_guidelines/16_no_cloud.png) | No cloud service is used. The one cloud SDK in `uv.lock`, `databricks-sdk`, is a dependency of MLflow itself, and my code never imports it; the DVC remote and the MLflow store are local folders. (The first capture said "no cloud SDK", which was wrong; I retook it on the host with the Pillow renderer.) |

## What I could not capture, and why

- **The architecture diagram.** `03_design/01_architecture` shows "Syntax error in text" where the diagram should be. The error was real: the last arrow was dotted with its label written inside the arrow (`serve -. images, scripts/build_multiarch.sh .-> hub`), and Mermaid's lexer does not accept a `.` in that kind of label, so it stopped at `.sh`. The HLD diagram has no dotted labels, which is why it rendered. I moved the label into the pipe form (`serve -.->|images, scripts/build_multiarch.sh| hub`). I could not retake it automatically: headless Firefox hangs on the VM, and pulling the Playwright image again stalled on the slow network. `03_design/01_architecture.png` is to be retaken from GitHub after push, where GitHub draws the Mermaid diagram.

- **The browser padlock.** Headless Chromium screenshots show only the page, not the address bar. My hand-taken Firefox screenshots do show the address bar, but Firefox hides the `https://` prefix, so none of them proves TLS by itself (`docs/screenshots/01_start.png` is the `docker compose ps` terminal, not a browser). The TLS proof is the terminal capture `11_guidelines/13_tls_certificate` (subject, issuer, protocol and `Verify return code: 0` against my CA).
- **The Docker Hub website.** hub.docker.com answers a headless browser with a Cloudflare "verify you are human" page, so I did not take those screenshots. Docker Hub's own API (`11_guidelines/17_dockerhub_api`) shows the same tags and platforms.
- **A fresh Spark ingest and validate in the evidence run.** Rerunning them needs the serve stack stopped, which I allow only for batch work, not for screenshots, so the live retrain reran only `features` and `train` (`11_guidelines/09_story_pipeline_log`). On 2026-11-11 I stopped the stack for a forced batch run, `dvc repro -f` as `manual-20261111-042650`: all 7 stages passed in 73.5 s of stage time, and the gate kept v4 because the candidate tied it at a mean MAE of 6.467. I did not capture that run's terminal output, but the console captures `02_pipeline_viz/01` and `02` show its stage table and its row in the run list. The full 7-stage Spark log in the gallery is still the recorded CI run of 2026-10-21 (`06_data_engineering/02_spark_repro_log`), and every stage's numbers since October are in `06_data_engineering/03_throughput_history`.
- **A promotion today.** The gate rejected today's candidate, so the story shows a rejection, not a new champion. The October run that promoted v4 is the champion run in `08_experiment_tracking`.
- **The rollback steps were retaken.** The first try failed because my capture script typed the wrong text into the version box (its label contains "="). The backend refused that value and nothing changed. I fixed the script and took 11 and 12 again; their caption times are a few minutes after the gate decision.
