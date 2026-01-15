.PHONY: build build-release up down restart logs logs-translation logs-all
.PHONY: server server_stop bash clean_reports
.PHONY: translation-server-up translation-server-down translation-server-restart
.PHONY: translation-server-logs translation-server-bash both-servers
.PHONY: evaluations run_test
.PHONY: test_prod test_suite calibrate generate_report
.PHONY: test_parallel_tests test_parallel_suites
.PHONY: simulate_test simulate_suite
.PHONY: mongo clean status help

# =============================================================================
# Help
# =============================================================================

help:
	@echo "Voice Translation POC - Available Make Targets"
	@echo ""
	@echo "Docker Compose:"
	@echo "  make build            Build Docker images"
	@echo "  make up               Start all services"
	@echo "  make down             Stop all services"
	@echo "  make restart          Restart all services"
	@echo "  make status           Show service status"
	@echo "  make logs             View original server logs"
	@echo "  make logs-translation View new server logs"
	@echo "  make logs-all         View all logs"
	@echo ""
	@echo "Original Server (vt-app on port 8765):"
	@echo "  make server           Run original WebSocket server"
	@echo "  make server_stop      Stop original server"
	@echo ""
	@echo "Translation Server (new architecture on port 8080):"
	@echo "  make translation-server-up      Start new server"
	@echo "  make translation-server-down    Stop new server"
	@echo "  make translation-server-restart Restart new server"
	@echo "  make translation-server-logs    View new server logs"
	@echo "  make translation-server-bash    Shell into new server"
	@echo "  make both-servers               Start both servers for comparison"
	@echo ""
	@echo "Testing:"
	@echo "  make evaluations      Run evaluations"
	@echo "  make test_prod        Run production test"
	@echo "  make test_suite       Run test suite"
	@echo ""
	@echo "Development:"
	@echo "  make bash             Shell into vt-app container"
	@echo "  make mongo            MongoDB shell"
	@echo "  make clean            Remove all containers and data"
	@echo ""

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

logs-translation:
	@docker compose logs -f translation-server

logs-all:
	@docker compose logs -f

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
# Translation Server (New Architecture)
# =============================================================================

translation-server-up:
	@echo "Starting translation server (new architecture)..."
	@docker compose up -d translation-server
	@echo "✓ Translation server started on port 8080"
	@echo "  View logs: make logs-translation"
	@echo "  WebSocket URL: ws://localhost:8080"

translation-server-down:
	@echo "Stopping translation server..."
	@docker compose stop translation-server
	@echo "✓ Translation server stopped"

translation-server-restart:
	@echo "Restarting translation server..."
	@docker compose restart translation-server
	@echo "✓ Translation server restarted"

translation-server-logs:
	@docker compose logs -f translation-server

translation-server-bash:
	@docker compose exec translation-server bash

# Start both servers for comparison
both-servers:
	@echo "Starting both servers for comparison..."
	@docker compose up -d vt-app translation-server
	@echo "✓ Both servers started"
	@echo ""
	@echo "Original server (vt-app):     ws://localhost:8765"
	@echo "New server (translation):     ws://localhost:8080"
	@echo ""
	@echo "View logs:"
	@echo "  make logs              # Original server"
	@echo "  make logs-translation  # New server"
	@echo "  make logs-all          # Both servers"

# =============================================================================
# Testing
# =============================================================================

evaluations:
	@echo "Running evaluations..."
	@docker compose exec -T vt-app poetry run run-evaluations

test_prod:
	@echo "Running test: $(SCENARIO)"
	@docker compose exec -T vt-app poetry run prod run-test $(SCENARIO)

test_suite:
	@echo "Running production test suite..."
	@docker compose exec -T vt-app poetry run prod run-suite production/tests/scenarios/

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
