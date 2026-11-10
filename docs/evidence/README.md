# Evidence Gallery

This folder holds screenshots and terminal captures for every line of the rubric and the guidelines (`docs/rubric.md`). I captured all of it on 2026-11-10 on the project VM, at commit `aeb8f83`, with the serve stack running. Each PNG has a dark strip on top with the time, the URL or command, and one line saying what it proves. Each terminal capture is also kept as a `.txt` next to its PNG, with the exact command on its `$` line.

**How it was made.** `docs/evidence/` was captured automatically by `scripts/capture_evidence.py` (Playwright in Docker, image `mcr.microsoft.com/playwright/python:v1.49.1-noble`, arm64), written by Claude Code under my direction. `scripts/capture_evidence_host.sh` runs the terminal commands on the host and drives the live story. The 11 user-manual screenshots in `docs/screenshots/` were taken by me by hand. No browser was installed on the VM; the Playwright image was removed afterwards.

**The API key** never appears in an image or a text file. The script types it into the console's masked field, checks the visible text of every page before it saves the screenshot, and stops if the key is there. Commands that use the key show the literal text `$OPS_API_KEY`. Every `.txt` file was searched for the key and the Grafana password before it was saved.

| Section | PNG | TXT |
|---|---:|---:|
| 01_ui | 18 | 0 |
| 02_pipeline_viz | 13 | 1 |
| 03_design | 25 | 2 |
| 04_implementation | 13 | 4 |
| 05_testing | 9 | 3 |
| 06_data_engineering | 13 | 4 |
| 07_source_control_ci | 13 | 8 |
| 08_experiment_tracking | 16 | 4 |
| 09_monitoring | 34 | 8 |
| 10_packaging | 19 | 8 |
| 11_guidelines | 49 | 22 |
| **Total** | **222** | **64** |

## The live story (11_guidelines/30_story_*)

This was the only part that changed state. With the ops runner started, I reset and started the replay from the console. Drift switched on 166 s later. `PM25DriftHigh` went pending, then firing, Alertmanager called the backend webhook, and the webhook wrote a retrain request. The runner paused the frontend and Grafana, ran `dvc repro` with the new cutoff (2020-04-04 04:00) and started them again 41 s later. **The gate rejected the new model**: its mean MAE was 6.007 and champion v4's was 5.948 on the same window, so it was not registered and v4 kept serving. Then I rolled back to v1 from the console and back to v4, and stopped and reset the replay. The step times are in `docs/metrics.md`, "Evidence run: drift to retrain, live".

Afterwards I put everything back: v4 champion and v1 previous, replay stopped at 25 Mar 2020, `params.yaml`, `dvc.lock` and `reports/` from git, the DVC outputs from the cache (`dvc status` clean), today's request file and `ops/episode.json` removed, the runner stopped (`30_story_23_final_state`). What stays, on purpose, is the history: the rejected run `b010fbb6` in MLflow, its rows in `reports/runs.jsonl` (so the console's last run is now the drift run), and the runner's log `ops/logs/rt-20261110-144028.log`.

## Rubric line to evidence

Paths are relative to this folder. `docs/screenshots/NN` means the hand-taken screenshot in `../screenshots/`.

### Demonstration: Web App Front-end UI/UX [3]

| Rubric line | Evidence | Caption |
|---|---|---|
| Intuitive for the problem | [01_ui/01_forecast_delhi.png](01_ui/01_forecast_delhi.png) to [07_forecast_kolkata.png](01_ui/07_forecast_kolkata.png) | The forecast page for each of the 7 cities: 1 h and 24 h PM2.5 cards in the CPCB colour, the category and the health advice |
| Easy for non-technical users | [01_ui/01_forecast_delhi.png](01_ui/01_forecast_delhi.png), [01_ui/18_user_manual.png](01_ui/18_user_manual.png) | Plain sentences, units on every number, a note that the dates are a 2020 replay |
| Foolproof | [01_ui/09_unknown_city_typed.png](01_ui/09_unknown_city_typed.png), [13_api_forecast_city_pune.png](01_ui/13_api_forecast_city_pune.png), [14_api_forecast.png](01_ui/14_api_forecast.png), [15_api_forecast_city_delhi.png](01_ui/15_api_forecast_city_delhi.png), [16_api_no_such_page.png](01_ui/16_api_no_such_page.png), [02_pipeline_viz/07_wrong_key.png](02_pipeline_viz/07_wrong_key.png) | Typing "Pune" finds no option; at the API an unknown city is 404, a missing one 422, a wrong case 404, an unknown route 404, all in one error shape; a wrong key shows no buttons |
| Free of UI errors | [01_ui/17_backend_down_message.png](01_ui/17_backend_down_message.png), [11_guidelines/30_story_09_back_in_a_few_minutes.png](11_guidelines/30_story_09_back_in_a_few_minutes.png) | Backend down: one plain sentence, no stack trace (a second frontend pointed at a dead `BACKEND_URL`); during a retrain the proxy shows "Back in a few minutes" |
| Good colours, shapes, look-and-feel | [01_ui/08_colour_legend.png](01_ui/08_colour_legend.png), [01_ui/02_forecast_chennai.png](01_ui/02_forecast_chennai.png) | The six CPCB categories and colours, rounded cards with readable text on each colour |
| Responsive | [01_ui/10_mobile_393px.png](01_ui/10_mobile_393px.png), [11_mobile_393px_full.png](01_ui/11_mobile_393px_full.png), [12_mobile_colour_legend.png](01_ui/12_mobile_colour_legend.png) | Phone width 393 x 852 (Chromium mobile emulation): the cards stack, nothing is cut off |
| User manual exists | [01_ui/18_user_manual.png](01_ui/18_user_manual.png), `docs/screenshots/01` to `13` | `docs/user_manual.md` rendered with its 11 screenshots |

### Demonstration: ML Pipeline Visualization [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| Separate UI screen for the pipeline incl. ingestion and engineering | [02_pipeline_viz/01_console_top.png](02_pipeline_viz/01_console_top.png), [03_dag.png](02_pipeline_viz/03_dag.png), [02_console_full_no_key.png](02_pipeline_viz/02_console_full_no_key.png) | `/console`: status boxes, the 7-stage DVC DAG coloured by status, the stage table |
| MLOps tool UIs | [02_pipeline_viz/11_grafana_pipeline.png](02_pipeline_viz/11_grafana_pipeline.png), [12_pushgateway.png](02_pipeline_viz/12_pushgateway.png), [08_experiment_tracking/02_runs.png](08_experiment_tracking/02_runs.png) | Grafana "AQ pipeline", the Pushgateway, MLflow, all linked from the console |
| Pipeline management console | [02_pipeline_viz/09_ops_section.png](02_pipeline_viz/09_ops_section.png), [10_console_full_with_key.png](02_pipeline_viz/10_console_full_with_key.png), [11_guidelines/30_story_01_replay_reset.png](11_guidelines/30_story_01_replay_reset.png), [30_story_16_rollback_to_v1.png](11_guidelines/30_story_16_rollback_to_v1.png) | Replay start/stop/reset, retrain and rollback buttons behind the masked key, and the buttons used live |
| Console of errors, failures and successful runs | [02_pipeline_viz/05_runs_and_failures.png](02_pipeline_viz/05_runs_and_failures.png), [13_pipeline_api.txt](02_pipeline_viz/13_pipeline_api.txt), [11_guidelines/30_story_14_console_after_retrain.png](11_guidelines/30_story_14_console_after_retrain.png) | Success and failure counts, the failed runs with stage and error, today's drift-triggered run at the top |
| Pipeline speed and throughput | [02_pipeline_viz/04_stage_table.png](02_pipeline_viz/04_stage_table.png), [11_grafana_pipeline.png](02_pipeline_viz/11_grafana_pipeline.png) | Duration, rows out and rows/sec per stage, and over time in Grafana |

### Software Engineering: Design Principle [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| Design document | [03_design/02_hld.png](03_design/02_hld.png), [31_docs_folder.txt](03_design/31_docs_folder.txt) | `docs/HLD.md` rendered: design choices with reasons |
| OO or functional paradigm stated | [03_design/05_paradigm.png](03_design/05_paradigm.png), [04_implementation/08_pipeline_features.png](04_implementation/08_pipeline_features.png), [07_backend_ops.png](04_implementation/07_backend_ops.png) | Functional pipeline stages, object-oriented services, and code of each kind |
| LLD with API endpoints and I/O specs | [03_design/03_lld.png](03_design/03_lld.png), [22_lld_error_contract.png](03_design/22_lld_error_contract.png) | `docs/LLD.md` rendered: every endpoint, its input, output, status codes and the error body |
| Architecture diagram | [03_design/01_architecture.png](03_design/01_architecture.png) | `docs/architecture.md` with the Mermaid diagram drawn and one paragraph per block |
| HLD diagram | [03_design/04_hld_diagram.png](03_design/04_hld_diagram.png) | The lifecycle diagram on its own |
| Loose coupling via configurable REST | [03_design/23_loose_coupling_client.png](03_design/23_loose_coupling_client.png), [30_frontend_never_imports_backend.txt](03_design/30_frontend_never_imports_backend.txt), [01_ui/17_backend_down_message.png](01_ui/17_backend_down_message.png) | The frontend's only door is `BACKEND_URL`; no frontend module imports backend code; the same image ran with another `BACKEND_URL` |
| FastAPI endpoints (design side) | [03_design/06_fastapi_docs.png](03_design/06_fastapi_docs.png), `07_endpoint_*` to `20_endpoint_*` (14 files), [21_lld_vs_openapi.png](03_design/21_lld_vs_openapi.png) | Swagger UI, each endpoint expanded, and the LLD's 14 endpoints next to the live `/openapi.json`: all match |

### Software Engineering: Implementation [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| Standard Python coding style | [04_implementation/20_ruff.txt](04_implementation/20_ruff.txt), [09_pyproject.png](04_implementation/09_pyproject.png) | `ruff check` and `ruff format --check` pass; the rule set |
| Logging | [04_implementation/01_common_logging_setup.png](04_implementation/01_common_logging_setup.png), [21_logging_everywhere.txt](04_implementation/21_logging_everywhere.txt) | One logging setup; every module uses it; no `print` in `src/` |
| Comprehensive exception handling | [04_implementation/02_backend_errors.png](04_implementation/02_backend_errors.png), [03_common_errors.png](04_implementation/03_common_errors.png), [04_common_stage_runner.png](04_implementation/04_common_stage_runner.png), [23_error_body_live.txt](04_implementation/23_error_body_live.txt) | Error types, handlers that give the LLD error body, a failing stage recorded with its error; live 404, 422, 404, 405 |
| Inline comments and docstrings | [04_implementation/06_backend_forecaster.png](04_implementation/06_backend_forecaster.png), [07_backend_ops.png](04_implementation/07_backend_ops.png), [05_backend_app.png](04_implementation/05_backend_app.png) | Docstrings on every class and function, comments where a choice needs a reason |
| Design document adhered to / APIs follow the spec | [04_implementation/22_api_tests_match_lld.txt](04_implementation/22_api_tests_match_lld.txt), [03_design/21_lld_vs_openapi.png](03_design/21_lld_vs_openapi.png) | The 8 tests that hold the code to the LLD, all passing |
| API-key check | [04_implementation/05_backend_app.png](04_implementation/05_backend_app.png) | `require_key`: Bearer token, `hmac.compare_digest`, 401 otherwise |
| Unit tests implemented | [05_testing/10_pytest_full.txt](05_testing/10_pytest_full.txt), [12_tests_per_module.txt](05_testing/12_tests_per_module.txt) | 367 passed; one test file per module |

### Software Engineering: Testing [1]

| Rubric line | Evidence | Caption |
|---|---|---|
| Test plan | [05_testing/01_test_plan.png](05_testing/01_test_plan.png) | `docs/test_plan.md`: scope, levels, environment, how to run |
| List of test cases | [05_testing/03_test_case_list.png](05_testing/03_test_case_list.png), [11_pytest_collect.txt](05_testing/11_pytest_collect.txt) | TC-01 to TC-49 and E2E-01 to E2E-23, and every collected pytest case |
| Test report with passed and failed counts | [05_testing/04_test_report.png](05_testing/04_test_report.png), [05_test_report_summary.png](05_testing/05_test_report_summary.png), [10_pytest_full.txt](05_testing/10_pytest_full.txt) | 367 run, 367 passed, 0 failed |
| Acceptance criteria defined and met | [05_testing/02_acceptance_criteria_defined.png](05_testing/02_acceptance_criteria_defined.png), [06_acceptance_criteria_met.png](05_testing/06_acceptance_criteria_met.png) | AC-1 to AC-7 defined in the plan, each met in the report |

### AIOps: Data Engineering [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| Ingestion/transformation pipeline with Spark | [06_data_engineering/10_ingest.png](06_data_engineering/10_ingest.png), [11_spark.png](06_data_engineering/11_spark.png), [20_spark_repro_log.txt](06_data_engineering/20_spark_repro_log.txt), [22_csv_to_parquet.txt](06_data_engineering/22_csv_to_parquet.txt) | Spark local mode, 2g driver, 8 shuffle partitions; 283 MB CSV to 65 MB Parquet; the Spark output of a full `dvc repro` |
| Throughput and speed | [06_data_engineering/21_stage_metrics.txt](06_data_engineering/21_stage_metrics.txt), [23_throughput_history.txt](06_data_engineering/23_throughput_history.txt), [01_metrics_ingest.png](06_data_engineering/01_metrics_ingest.png), [03_metrics_validate.png](06_data_engineering/03_metrics_validate.png), [04_metrics_features.png](06_data_engineering/04_metrics_features.png), [11_guidelines/30_story_11_pipeline_log.txt](11_guidelines/30_story_11_pipeline_log.txt) | Seconds and rows/sec per stage: ingest about 444,000 rows/s, validate 131,000, features 28,000; today's live features run 27,607 rows/s |
| Spark vs pandas benchmark | [06_data_engineering/02_spark_vs_pandas.png](06_data_engineering/02_spark_vs_pandas.png), [13_bench_pandas_ingest.png](06_data_engineering/13_bench_pandas_ingest.png) | pandas was about twice as fast on this small data; the benchmark script |

### AIOps: Source Control & CI [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| CI implemented using DVC | [07_source_control_ci/20_ci_run.txt](07_source_control_ci/20_ci_run.txt), [11_ci_sh.png](07_source_control_ci/11_ci_sh.png), [10_pre_commit.png](07_source_control_ci/10_pre_commit.png) | A full passing `scripts/ci.sh` run: ruff, format, 367 tests, `dvc status`, `dvc status -c`; the pre-commit hook |
| DVC DAG representing the CI pipeline | [07_source_control_ci/01_dvc_dag.txt](07_source_control_ci/01_dvc_dag.txt), [02_dvc_yaml.png](07_source_control_ci/02_dvc_yaml.png), [12_params_yaml.png](07_source_control_ci/12_params_yaml.png) | `dvc dag` and `dvc.yaml`: the 7 stages with deps, params and outputs |
| Git and DVC for source, data and model versioning | [07_source_control_ci/06_git_log.txt](07_source_control_ci/06_git_log.txt), [07_data_versioned_by_dvc.txt](07_source_control_ci/07_data_versioned_by_dvc.txt), [08_model_versions_in_git.txt](07_source_control_ci/08_model_versions_in_git.txt), [03_dvc_status.txt](07_source_control_ci/03_dvc_status.txt), [04_dvc_status_remote.txt](07_source_control_ci/04_dvc_status_remote.txt), [05_dvc_remote.txt](07_source_control_ci/05_dvc_remote.txt), [09_gitignore.png](07_source_control_ci/09_gitignore.png) | Git history, data only as a `.dvc` pointer, model and data hashes in `dvc.lock` commits, a local DVC remote in sync |

### AIOps: Experiment Tracking [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| Tracking while models are built | [08_experiment_tracking/01_experiments.png](08_experiment_tracking/01_experiments.png), [02_runs.png](08_experiment_tracking/02_runs.png), [22_all_runs.txt](08_experiment_tracking/22_all_runs.txt) | Every training run in the `aq-pm25` experiment, with trigger and gate result |
| Metrics, parameters and artifacts | [08_experiment_tracking/03_champion_run_overview.png](08_experiment_tracking/03_champion_run_overview.png), [04_champion_run_metrics.png](08_experiment_tracking/04_champion_run_metrics.png), [05_artifact_feature_importance.png](08_experiment_tracking/05_artifact_feature_importance.png), [06_artifact_per_city_mae.png](08_experiment_tracking/06_artifact_per_city_mae.png), [07_artifact_drift_baseline.png](08_experiment_tracking/07_artifact_drift_baseline.png), [08_artifact_residuals.png](08_experiment_tracking/08_artifact_residuals.png), [21_champion_run_metrics.txt](08_experiment_tracking/21_champion_run_metrics.txt) | 94 metrics, 24 parameters, artifacts incl. the feature importance plot |
| Provisions beyond autolog | [08_experiment_tracking/20_champion_run_tags.txt](08_experiment_tracking/20_champion_run_tags.txt), [04_champion_run_metrics.png](08_experiment_tracking/04_champion_run_metrics.png), [30_train_logging.png](08_experiment_tracking/30_train_logging.png) | Tags `git_commit`, `git_dirty`, `dvc_data_md5`, `features_md5`, `cutoff`, `trigger`, `promotion`; per-city MAE; drift baseline |
| Model registry | [08_experiment_tracking/09_registry_models.png](08_experiment_tracking/09_registry_models.png), [10_registry_versions.png](08_experiment_tracking/10_registry_versions.png), [11_registry_v4.png](08_experiment_tracking/11_registry_v4.png), [23_registry_aliases.txt](08_experiment_tracking/23_registry_aliases.txt) | Versions 1 and 4 with the `previous` and `champion` aliases |

### AIOps: Exporter Instrumentation & Visualization [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| Prometheus instrumentation | [09_monitoring/22_backend_metrics.png](09_monitoring/22_backend_metrics.png), [32_backend_metrics.txt](09_monitoring/32_backend_metrics.txt), [30_model_server_metrics.txt](09_monitoring/30_model_server_metrics.txt), [31_frontend_metrics.txt](09_monitoring/31_frontend_metrics.txt), [33_pushgateway_metrics.txt](09_monitoring/33_pushgateway_metrics.txt), [34_mlflow_metrics.txt](09_monitoring/34_mlflow_metrics.txt) | `/metrics` of the backend, model server, frontend, the pipeline through the Pushgateway, and MLflow |
| All components monitored | [09_monitoring/01_prometheus_targets.png](09_monitoring/01_prometheus_targets.png), [35_targets_api.txt](09_monitoring/35_targets_api.txt), [04_prometheus_query_up.png](09_monitoring/04_prometheus_query_up.png), [40_prometheus_yml.png](09_monitoring/40_prometheus_yml.png), [37_retention_scrape.txt](09_monitoring/37_retention_scrape.txt) | 9 scrape jobs, all up; every 15 s, 2 days retention |
| Information points and alert rules | [09_monitoring/02_prometheus_rules.png](09_monitoring/02_prometheus_rules.png), [03_prometheus_alerts.png](09_monitoring/03_prometheus_alerts.png), [41_alerts_yml.png](09_monitoring/41_alerts_yml.png), [36_promtool_rules.txt](09_monitoring/36_promtool_rules.txt), [43_alerts_test.png](09_monitoring/43_alerts_test.png), [06_alertmanager_alerts.png](09_monitoring/06_alertmanager_alerts.png), [07_alertmanager_status.png](09_monitoring/07_alertmanager_status.png), [42_alertmanager_yml.png](09_monitoring/42_alertmanager_yml.png) | Drift, error-ratio, 5xx-rate, model-server, target-down and failed-stage rules, checked by promtool; Alertmanager routes to the backend |
| Grafana in near real time | [09_monitoring/08_grafana_aq_service.png](09_monitoring/08_grafana_aq_service.png), [09_grafana_aq_pipeline.png](09_monitoring/09_grafana_aq_pipeline.png), `10_panel_*` to `21_panel_*` (12 files), [05_prometheus_query_rate.png](09_monitoring/05_prometheus_query_rate.png), [11_guidelines/30_story_08_grafana_drift.png](11_guidelines/30_story_08_grafana_drift.png) | Both dashboards, key panels one by one, and the service dashboard during the live drift |

### AIOps: Software Packaging [2]

| Rubric line | Evidence | Caption |
|---|---|---|
| MLflow for APIfication of the model | [10_packaging/24_model_serving.txt](10_packaging/24_model_serving.txt), [06_dockerfile_model_server.png](10_packaging/06_dockerfile_model_server.png), [11_model_server_proxy.png](10_packaging/11_model_server_proxy.png) | `mlflow models serve` answers `/ping` and `/invocations` with predictions and the version |
| MLproject for identical environments | [10_packaging/01_mlproject.png](10_packaging/01_mlproject.png), [02_python_env.png](10_packaging/02_python_env.png), [26_mlproject_entry_points.txt](10_packaging/26_mlproject_entry_points.txt) | Entry points and the pinned environment, the same versions as `uv.lock` |
| FastAPI for the APIs the UI needs | [10_packaging/25_backend_forecast.txt](10_packaging/25_backend_forecast.txt), [27_health.txt](10_packaging/27_health.txt), [03_design/06_fastapi_docs.png](03_design/06_fastapi_docs.png) | `/forecast` with model version, run ID and commit; `/health` |
| Backend and frontend dockerized | [10_packaging/04_dockerfile_frontend.png](10_packaging/04_dockerfile_frontend.png), [05_dockerfile_backend.png](10_packaging/05_dockerfile_backend.png), [07_dockerfile_mlflow.png](10_packaging/07_dockerfile_mlflow.png), [08_dockerfile_pipeline.png](10_packaging/08_dockerfile_pipeline.png), [09_caddyfile.png](10_packaging/09_caddyfile.png), [22_docker_images.txt](10_packaging/22_docker_images.txt) | One Dockerfile per service |
| docker compose with two separate services | [10_packaging/03_docker_compose.png](10_packaging/03_docker_compose.png), [20_compose_ps.txt](10_packaging/20_compose_ps.txt), [21_docker_stats.txt](10_packaging/21_docker_stats.txt) | frontend and backend as separate services, all 10 up and healthy, each under its `mem_limit` |
| Multi-arch images | [10_packaging/23_dockerhub_inspect.txt](10_packaging/23_dockerhub_inspect.txt), [10_build_multiarch.png](10_packaging/10_build_multiarch.png) | All 5 images with linux/amd64 and linux/arm64 |

### Mandatory documents

| Document | Evidence |
|---|---|
| Architecture diagram with block explanations | [03_design/01_architecture.png](03_design/01_architecture.png) |
| HLD with design choices and rationale | [03_design/02_hld.png](03_design/02_hld.png) |
| LLD with endpoint definitions and I/O specs | [03_design/03_lld.png](03_design/03_lld.png) |
| Test plan and test cases | [05_testing/01_test_plan.png](05_testing/01_test_plan.png), [03_test_case_list.png](05_testing/03_test_case_list.png) |
| User manual for non-technical users | [01_ui/18_user_manual.png](01_ui/18_user_manual.png) |

### Guidelines

| Guideline | Evidence | Caption |
|---|---|---|
| Reproducible via git commit + MLflow run ID | [11_guidelines/01_reproducibility_tags.txt](11_guidelines/01_reproducibility_tags.txt), [02_reproduce_readme.png](11_guidelines/02_reproduce_readme.png), [03_ac6_reproducible.png](11_guidelines/03_ac6_reproducible.png) | A forecast names its version, run and commit; the run's tags lead to the code and data; a rebuild matched |
| EDA and documented data biases | [11_guidelines/04_eda.png](11_guidelines/04_eda.png), [05_data_biases.png](11_guidelines/05_data_biases.png), [06_data_notes.png](11_guidelines/06_data_notes.png) | EDA with its six figures, nine biases and what I do about each |
| Rollback for failed deployments | [11_guidelines/30_story_16_rollback_to_v1.png](11_guidelines/30_story_16_rollback_to_v1.png), [30_story_17_serving_v1.txt](11_guidelines/30_story_17_serving_v1.txt), [30_story_18_rollback_to_v4.png](11_guidelines/30_story_18_rollback_to_v4.png), [30_story_19_serving_v4.txt](11_guidelines/30_story_19_serving_v4.txt), [10_rollback_cli.txt](11_guidelines/10_rollback_cli.txt), [11_rollback_script.png](11_guidelines/11_rollback_script.png), [12_ac5_rollback.png](11_guidelines/12_ac5_rollback.png), [13_failure_handling.png](11_guidelines/13_failure_handling.png) | "Rolled back from version 4 to version 1.", the model server swapped, then back to v4 |
| Automated monitoring and alerting | [11_guidelines/30_story_03_drift_yes.png](11_guidelines/30_story_03_drift_yes.png), [30_story_03_drift_api.txt](11_guidelines/30_story_03_drift_api.txt), [30_story_04_alert_pending.png](11_guidelines/30_story_04_alert_pending.png), [30_story_05_alert_firing.png](11_guidelines/30_story_05_alert_firing.png), [30_story_06_alertmanager.png](11_guidelines/30_story_06_alertmanager.png), [30_story_08_grafana_drift.png](11_guidelines/30_story_08_grafana_drift.png), [20_ac3_drift.png](11_guidelines/20_ac3_drift.png) | Drift YES (4 of 4 needed), `PM25DriftHigh` pending then firing, Alertmanager, Grafana |
| Automated retraining | [11_guidelines/30_story_00_runner_started.txt](11_guidelines/30_story_00_runner_started.txt), [30_story_07_retrain_request.txt](11_guidelines/30_story_07_retrain_request.txt), [30_story_09_back_in_a_few_minutes.png](11_guidelines/30_story_09_back_in_a_few_minutes.png), [30_story_10_compose_during_retrain.txt](11_guidelines/30_story_10_compose_during_retrain.txt), [30_story_11_pipeline_log.txt](11_guidelines/30_story_11_pipeline_log.txt), [30_story_12_gate_decision.txt](11_guidelines/30_story_12_gate_decision.txt), [30_story_13_request_final.txt](11_guidelines/30_story_13_request_final.txt), [30_story_14_console_after_retrain.png](11_guidelines/30_story_14_console_after_retrain.png), [30_story_15_served_version.txt](11_guidelines/30_story_15_served_version.txt), [30_story_22_mlflow_rejected_run.png](11_guidelines/30_story_22_mlflow_rejected_run.png), [21_ops_runner.png](11_guidelines/21_ops_runner.png), [22_retrain_e2e.png](11_guidelines/22_retrain_e2e.png) | The webhook's request, `dvc repro` with the new cutoff, the gate's decision (rejected, v4 stays), the run in MLflow; the October run that promoted v4 |
| Encryption and security | [11_guidelines/40_https_redirect.txt](11_guidelines/40_https_redirect.txt), [41_tls_certificate.txt](11_guidelines/41_tls_certificate.txt), [42_ops_auth.txt](11_guidelines/42_ops_auth.txt), [43_secrets_not_in_git.txt](11_guidelines/43_secrets_not_in_git.txt), [44_non_root_containers.txt](11_guidelines/44_non_root_containers.txt), [45_hmac_check.txt](11_guidelines/45_hmac_check.txt), [46_security_hld.png](11_guidelines/46_security_hld.png), [02_pipeline_viz/07_wrong_key.png](02_pipeline_viz/07_wrong_key.png), `docs/screenshots/01` (browser warning, by hand) | http redirects to https; both certificates verify against my CA (`Verify return code: 0`); 401 without or with a wrong key, 200 with it; `.env` and keys ignored, the key in no commit; no root containers |
| Docker Hub | [11_guidelines/52_dockerhub_api.txt](11_guidelines/52_dockerhub_api.txt), [51_dockerhub_tags.txt](11_guidelines/51_dockerhub_tags.txt), [10_packaging/23_dockerhub_inspect.txt](10_packaging/23_dockerhub_inspect.txt), [53_dockerhub_readme.png](11_guidelines/53_dockerhub_readme.png) | Docker Hub's API: `latest` and `0.1.0` of all 5 images, each linux/amd64 + linux/arm64 |
| No cloud platforms | [11_guidelines/50_no_cloud.txt](11_guidelines/50_no_cloud.txt), [07_source_control_ci/05_dvc_remote.txt](07_source_control_ci/05_dvc_remote.txt) | No cloud SDK in `uv.lock`; the DVC remote and MLflow store are local folders |
| State restored after the story | [11_guidelines/30_story_20_replay_stopped.png](11_guidelines/30_story_20_replay_stopped.png), [30_story_21_replay_reset_again.png](11_guidelines/30_story_21_replay_reset_again.png), [30_story_23_final_state.txt](11_guidelines/30_story_23_final_state.txt) | v4 champion, replay reset, no new request file, `dvc status` clean, no alert firing |

## What I could not capture, and why

- **The browser padlock.** Headless Chromium screenshots show only the page, not the address bar. The TLS proof is the terminal capture `41_tls_certificate.txt` (subject, issuer, protocol, `Verify return code: 0` against my CA) and the redirect in `40_https_redirect.txt`. My hand-taken `docs/screenshots/01_start.png` shows the browser side.
- **The Docker Hub website.** hub.docker.com answers a headless browser with a Cloudflare "verify you are human" page, so I did not take those screenshots. Docker Hub's own API (`52_dockerhub_api.txt`) and `docker buildx imagetools inspect` (`10_packaging/23_dockerhub_inspect.txt`) show the same tags and platforms.
- **A fresh Spark ingest and validate.** Rerunning them needs the serve stack stopped, which the rules allow only for batch work, not for screenshots. The live retrain reran `features` and `train` (Spark output in `30_story_11_pipeline_log.txt`); the full 7-stage Spark output is the recorded CI run of 2026-10-21 (`06_data_engineering/20_spark_repro_log.txt`), and every stage's numbers since October are in `23_throughput_history.txt`.
- **A promotion.** The gate rejected today's candidate, so the story shows a rejection, not a new champion. The October run that promoted v4 is documented in `22_retrain_e2e.png` and its MLflow run is the champion run in section 08.
- **Two story steps were retaken.** The Grafana view (step 8) failed at first because the runner had stopped Grafana for the retrain, so I took it when Grafana was back, with the replay still running. The served-version capture (step 15) and the rollbacks (steps 16 to 19) were retaken after I fixed two bugs in my capture script (a wrong JSON path, and a label containing "=" that put the wrong text into the version box). The timestamps in the captions show this order.
