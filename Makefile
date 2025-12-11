.PHONY: build up down restart logs
.PHONY: server server_stop bash clean_reports
.PHONY: evaluations run_test
.PHONY: test_prod test_suite calibrate
.PHONY: mongo clean status

# =============================================================================
# Docker Compose Targets
# =============================================================================

build:
	@echo "Building Docker images..."
	@docker compose build
	@echo "✓ Images built successfully"

up:
	@echo "Starting services..."
	@docker compose up -d
	@echo "✓ Services started"
	@echo ""
	@docker compose ps

down:
	@echo "Stopping services..."
	@docker compose down
	@echo "✓ Services stopped (data preserved)"

restart:
	@echo "Restarting services..."
	@docker compose restart
	@echo "✓ Services restarted"

logs:
	@docker compose logs -f vt-app

status:
	@docker compose ps

# =============================================================================
# Server Management
# =============================================================================

server:
	@echo "Starting WebSocket server...."
	@poetry run speech-poc serve --host 0.0.0.0 --port 8765 --from-language en-US --to-language es --voice alloy --testing
	@echo "  View logs: make logs"

server_stop:
	@echo "Stopping server..."
	@docker compose down
	@echo "✓ Server stopped"

# =============================================================================
# Testing
# =============================================================================

evaluations:
	@echo "Running evaluations..."
	@docker compose exec -T vt-app poetry run run-evaluations

run_test:
	@if [ -z "$(TEST_ID)" ]; then \
		echo "Error: TEST_ID not specified"; \
		echo "Usage: make run_test TEST_ID=production/tests/scenarios/test_case_id"; \
		exit 1; \
	fi
	@docker compose exec -T vt-app poetry run run-evaluations --test-case $(TEST_ID)

test_prod:
	@echo "Running test: $(SCENARIO)"
	@docker compose exec -T vt-app poetry run prod run-test $(SCENARIO)

test_suite:
	@echo "Running production test suite..."
	@docker compose exec -T vt-app poetry run prod run-suite production/tests/scenarios/

calibrate:
	@echo "Running metrics calibration..."
	@docker compose exec -T vt-app poetry run prod calibrate $(ARGS)

# =============================================================================
# Development
# =============================================================================

bash:
	@docker compose exec vt-app bash

mongo:
	@docker compose exec mongodb mongosh vt_metrics

clean_reports:
	@echo "Removing generated reports..."
	@rm -rf reports/*.pdf
	@echo "✓ Reports cleaned"

# =============================================================================
# Cleanup
# =============================================================================

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
