# Backend: FastAPI service (forecast, pipeline views, ops endpoints, metrics).
# Build from the repository root:
#   docker build -f docker/backend/Dockerfile -t aq-backend .
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
WORKDIR /app

COPY docker/model_server/requirements.txt /tmp/model_server/requirements.txt
COPY docker/backend/requirements.txt /tmp/backend/requirements.txt
RUN pip install --no-cache-dir -r /tmp/backend/requirements.txt

COPY src/__init__.py src/__init__.py
COPY src/common src/common
COPY src/backend src/backend
COPY src/monitoring src/monitoring
COPY src/pipeline/__init__.py src/pipeline/registry.py src/pipeline/
COPY params.yaml params.yaml

# Mounted at run time (compose): data/features, reports, ops. Not baked in.
USER app
ENV BACKEND_PORT=8000 MLFLOW_DISABLE_AGENT_HINT=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD curl -fs http://localhost:8000/health || exit 1

CMD ["python", "-m", "src.backend.main"]
