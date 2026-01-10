FROM node:20-bullseye-slim AS frontend-build

WORKDIR /app/frontend
COPY client_web/frontend/package.json client_web/frontend/package-lock.json ./
RUN npm ci
COPY client_web/frontend/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

COPY client_web/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY client_web/src /app/src
COPY --from=frontend-build /app/frontend/dist /app/src/acs_webclient/web/static

EXPOSE 8000
CMD ["uvicorn", "acs_webclient.main:app", "--host", "0.0.0.0", "--port", "8000"]
