# Pipeline (batch profile): Spark in local mode + DVC + MLflow, runs `dvc repro`.
# The project folder is mounted at /app by compose, so the image holds only the
# environment. Build from the repository root:
#   docker build -f docker/pipeline/Dockerfile -t aq-pipeline .
FROM python:3.12-slim

# Spark needs a JRE; git is needed by DVC and for the commit hash in MLflow tags.
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless git libgomp1 procps \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
WORKDIR /app

COPY docker/pipeline/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --retries 10 --timeout 60 -r /tmp/requirements.txt

USER app
ENV PYTHONPATH=/app MLFLOW_DISABLE_AGENT_HINT=1
CMD ["dvc", "repro"]
