# MLflow tracking server and registry, with its Prometheus exporter.
# It reuses the model-server image, which already has MLflow, and adds only
# prometheus-flask-exporter, which `mlflow server --expose-prometheus` needs.
# Build from the repository root after aq-model-server:
#   docker build -f docker/mlflow/Dockerfile -t aq-mlflow .
ARG BASE=aq-model-server
FROM ${BASE}

USER root
RUN pip install --no-cache-dir --retries 10 --timeout 60 prometheus-flask-exporter==0.23.2
USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD curl -fs http://localhost:5000/health || exit 1
