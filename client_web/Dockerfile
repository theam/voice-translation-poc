FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir poetry
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root
COPY src ./src
COPY --from=frontend /app/src/acs_webclient/web/static ./src/acs_webclient/web/static
EXPOSE 8000
CMD ["poetry", "run", "uvicorn", "acs_webclient.main:app", "--host", "0.0.0.0", "--port", "8000"]
