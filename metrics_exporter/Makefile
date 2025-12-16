.PHONY: build up down restart logs status clean
.PHONY: test dev rebuild bash exec

IMAGE_NAME ?= metrics-exporter
TAG ?= latest
DOCKERFILE ?= docker/Dockerfile
PORT ?= 9100
RUN_FLAGS ?=

# =============================================================================
# Docker Compose Targets
# =============================================================================

build:
	@echo "Building metrics exporter image..."
	@docker compose build
	@echo "✓ Image built successfully"

up:
	@echo "Starting metrics stack (Prometheus, Grafana, Metrics Exporter)..."
	@docker compose up -d
	@echo "✓ Metrics stack started"
	@echo ""
	@echo "Services available at:"
	@echo "  - Metrics Exporter: http://localhost:9100/metrics"
	@echo "  - Prometheus:       http://localhost:9090"
	@echo "  - Grafana:          http://localhost:3000"
	@echo ""
	@docker compose ps

down:
	@echo "Stopping metrics stack..."
	@docker compose down
	@echo "✓ Metrics stack stopped (data preserved)"

restart:
	@echo "Restarting metrics stack..."
	@docker compose restart
	@echo "✓ Metrics stack restarted"

logs:
	@docker compose logs -f

status:
	@docker compose ps

clean:
	@echo "⚠️  This will remove all containers, networks, and volumes (DELETE ALL DATA)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker compose down -v; \
		echo "✓ All resources removed"; \
	else \
		echo "Cancelled"; \
	fi

# =============================================================================
# Development & Testing
# =============================================================================

dev:
	@echo "Starting metrics stack in development mode with hot reload..."
	@echo "⚡ File changes in app/ will automatically restart the service"
	@echo ""
	@docker compose up

rebuild:
	@echo "Rebuilding image (use after updating requirements.txt)..."
	@docker compose down
	@docker compose build --no-cache
	@docker compose up -d
	@echo "✓ Image rebuilt and services restarted"

bash:
	@echo "Opening interactive shell in metrics_exporter container..."
	@docker compose run --rm --entrypoint bash metrics_exporter

exec:
	@if [ -z "$(CMD)" ]; then \
		echo "Error: CMD not specified"; \
		echo "Usage: make exec CMD='python -c \"import sys; print(sys.version)\"'"; \
		exit 1; \
	fi
	@echo "Executing command in new container..."
	@docker compose run --rm --entrypoint bash metrics_exporter -c "$(CMD)"

test:
	@echo "Running unit tests..."
	@docker compose run --rm --entrypoint bash metrics_exporter -c "pytest app/tests"
