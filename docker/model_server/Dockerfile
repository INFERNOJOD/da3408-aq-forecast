# Model server: mlflow models serve + metrics proxy + champion watcher.
# Build from the repository root:
#   docker build -f docker/model_server/Dockerfile -t aq-model-server .
FROM python:3.12-slim

# LightGBM needs the OpenMP runtime, which the slim image does not include.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY docker/model_server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Only the code the server needs: the proxy, the registry client and helpers.
COPY src/__init__.py src/__init__.py
COPY src/common src/common
COPY src/model_server src/model_server
COPY src/pipeline/__init__.py src/pipeline/registry.py src/pipeline/

USER app
ENV MLFLOW_DISABLE_AGENT_HINT=1 MODEL_PORT=5001 METRICS_PORT=8001
EXPOSE 5001 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD curl -fs http://localhost:5001/ping || exit 1

CMD ["python", "-m", "src.model_server.serve"]
