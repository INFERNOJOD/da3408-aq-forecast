# Frontend: Streamlit pages that talk to the backend over REST only.
# Build from the repository root:
#   docker build -f docker/frontend/Dockerfile -t aq-frontend .
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
WORKDIR /app

COPY docker/frontend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Only the frontend and the two shared helpers it imports (logging, errors).
COPY src/__init__.py src/__init__.py
COPY src/common/__init__.py src/common/errors.py src/common/logging_setup.py src/common/
COPY src/frontend src/frontend
# Hides Streamlit's developer toolbar and menu from users.
COPY .streamlit/config.toml .streamlit/config.toml

USER app
ENV PYTHONPATH=/app BACKEND_URL=http://backend:8000 UI_METRICS_PORT=8502
EXPOSE 8501 8502

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fs http://localhost:8501/_stcore/health || exit 1

# main.py starts the metrics exporter before Streamlit (see its docstring).
CMD ["python", "-m", "src.frontend.main", "--server.port=8501", \
     "--server.address=0.0.0.0", "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
