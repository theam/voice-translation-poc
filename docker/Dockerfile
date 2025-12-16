# syntax=docker/dockerfile:1

FROM python:3.9.6-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (build-essential only if you really need to compile wheels)
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install PyDev and Poetry into the global Python env and disable venv creation
RUN pip install --no-cache-dir \
        poetry \
        pydevd-pycharm~=252.26830.99 \
    && poetry config virtualenvs.create false


# Install Python deps using Poetry (better caching)
COPY . .
RUN poetry install --no-interaction --no-ansi --with evaluations

# Example CMD – adapt to your app
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
