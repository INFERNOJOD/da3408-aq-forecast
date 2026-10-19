# Official Evaluation Rubric (DA3408)

Total: 25 marks.

## Demonstration [5]
- **Web App Front-end UI/UX [3]:** intuitive for the problem; easy for non-technical users; foolproof; free of UI errors; good colours, shapes, look-and-feel; responsive; user manual exists.
- **ML Pipeline Visualization [2]:** separate UI screen visualizing the ML pipeline incl. data ingestion/engineering (or MLOps tool UIs, orchestrated seamlessly); pipeline management console; console of errors, failures and successful runs; pipeline speed and throughput.

## Software Engineering [5]
- **Design Principle [2]:** design document; OO or functional paradigm stated; LLD with API endpoint definitions and I/O specs; architecture diagram; HLD diagram; strict loose coupling - frontend and backend independent, connected only via configurable REST API calls.
- **Implementation [2]:** standard Python coding style; logging; comprehensive exception handling; design document strictly adhered to; inline code comments; APIs follow the design doc interface spec; unit tests implemented.
- **Testing [1]:** test plan; list of test cases; test report with number of test cases passed and failed; acceptance criteria defined and met.

## AIOps Implementation [10]
- **Data Engineering [2]:** data ingestion/transformation pipeline using Ray or Spark or Kubernetes; throughput and speed of the pipeline.
- **Source Control & CI [2]:** CI implemented using DVC; DVC DAG representing the CI pipeline; Git, Git LFS and/or DVC for source, data, model versioning.
- **Experiment Tracking [2]:** tracking while models are built; metrics, parameters and artifacts tracked; provisions beyond autolog.
- **Exporter Instrumentation & Visualization [2]:** Prometheus instrumentation; information points monitored; all components monitored; Grafana visualization in near real time.
- **Software Packaging [2]:** MLflow for APIfication of the model for inference; MLprojects for identical dev vs test environments; FastAPI for the APIs the UI needs; backend and frontend dockerized; docker compose with them as two separate services.

## Viva [5]
Explain the whole project; questions from Assignments 1-10; MLOps tools and use cases; design and implementation choices; defend choices when challenged.

## Mandatory documents
- Architecture diagram with block explanations
- HLD document with design choices and rationale
- LLD with endpoint definitions and I/O specs
- Test plan and test cases
- User manual for non-technical users

## Guidelines also require
- Every experiment reproducible via git commit hash + MLflow run ID
- EDA and documented data biases
- Rollback for failed deployments
- Automated monitoring and alerting
- Automated retraining
- Encryption/security measures
- Docker Hub
- No cloud platforms
