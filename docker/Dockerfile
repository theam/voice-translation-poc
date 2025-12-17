# syntax=docker/dockerfile:1

# ------------------------------------------------------------
# Base image can be swapped at build time (public locally, private in CI/prod)
#   Local: docker build -t myapp:dev .
#   CI:    docker build --build-arg PYTHON_BASE=myreg.company.com/sanitized/python:3.12-slim -t myapp:sha .
# ------------------------------------------------------------
ARG PYTHON_BASE=python:3.12-slim
FROM ${PYTHON_BASE}

# ------------------------------------------------------------
# Runtime/env defaults
# ------------------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ------------------------------------------------------------
# Optional dev tools (e.g., PyCharm debugger)
#   Local: docker build --build-arg INSTALL_DEVTOOLS=true -t myapp:dev .
# ------------------------------------------------------------
ARG INSTALL_DEVTOOLS=false

# ------------------------------------------------------------
# System deps
# NOTE: build-essential is only needed when compiling wheels; keep it if you need it.
# ------------------------------------------------------------
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# Install Poetry (global) and configure it to NOT create venvs
# ------------------------------------------------------------
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false

# Dev-only Python tooling (kept out of prod by default)
RUN if [ "$INSTALL_DEVTOOLS" = "true" ]; then \
        pip install --no-cache-dir pydevd-pycharm~=252.26830.99 ; \
    fi

# ------------------------------------------------------------
# Dependency install with good layer caching:
#  1) Copy only dependency manifests first
#  2) Install deps
#  3) Copy the rest of the source
# ------------------------------------------------------------
COPY README.md pyproject.toml poetry.lock* ./

# Install only dependencies first (not the project itself)
# This allows Docker to cache this layer when only source code changes
RUN poetry lock
RUN poetry install --no-root --no-interaction --no-ansi --with evaluations

# Now copy the application code (this layer changes most often)
COPY . .

# Install the project itself now that source code is available
RUN poetry lock
RUN poetry install --no-interaction --no-ansi --with evaluations

# ------------------------------------------------------------
# Default command (adapt to your app)
# ------------------------------------------------------------
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
