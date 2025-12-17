.PHONY: build build-release up down restart logs
.PHONY: server server_stop bash clean_reports
.PHONY: evaluations run_test
.PHONY: test_prod test_suite calibrate generate_report
.PHONY: test_parallel_tests test_parallel_suites
.PHONY: simulate_test simulate_suite
.PHONY: mongo clean status

# =============================================================================
# Docker Compose Targets
# =============================================================================
#
# Build arguments:
#   PYTHON_BASE - Custom Python base image (default: python:3.12-slim)
#   INSTALL_DEVTOOLS - Install development tools like PyCharm debugger (default: false)
#
# Examples:
#   make build                                              # Use defaults
#   make build PYTHON_BASE=myregistry.com/python:3.12-slim # Custom base image
#   make build INSTALL_DEVTOOLS=true                        # With dev tools
#   make build PYTHON_BASE=custom:image INSTALL_DEVTOOLS=true # Both
# =============================================================================
#
# Release Build (for CI/CD):
#   IMAGE_NAME - Docker image name (required)
#   IMAGE_TAG - Docker image tag (required)
#   GIT_SHA - Git commit SHA for labels (optional)
#   GIT_BRANCH - Git branch name for labels (optional)
#   BUILD_DATE - Build timestamp (optional, defaults to now)
#   PYTHON_BASE - Python base image (optional)
#
# Examples:
#   make build-release IMAGE_NAME=myapp IMAGE_TAG=v1.0.0 GIT_SHA=abc1234
#   make build-release IMAGE_NAME=myapp IMAGE_TAG=main-abc1234 GIT_BRANCH=main
# =============================================================================

build:
	@echo "Building Docker images..."
	@BUILD_ARGS=""; \
	if [ -n "$(PYTHON_BASE)" ]; then \
		echo "Using custom Python base image: $(PYTHON_BASE)"; \
		BUILD_ARGS="$$BUILD_ARGS --build-arg PYTHON_BASE=$(PYTHON_BASE)"; \
	fi; \
	if [ -n "$(INSTALL_DEVTOOLS)" ]; then \
		echo "Installing dev tools: $(INSTALL_DEVTOOLS)"; \
		BUILD_ARGS="$$BUILD_ARGS --build-arg INSTALL_DEVTOOLS=$(INSTALL_DEVTOOLS)"; \
	fi; \
	docker compose build $$BUILD_ARGS
	@echo "✓ Images built successfully"

build-release:
	@if [ -z "$(IMAGE_NAME)" ]; then \
		echo "Error: IMAGE_NAME is required"; \
		echo "Usage: make build-release IMAGE_NAME=myapp IMAGE_TAG=v1.0.0"; \
		exit 1; \
	fi
	@if [ -z "$(IMAGE_TAG)" ]; then \
		echo "Error: IMAGE_TAG is required"; \
		echo "Usage: make build-release IMAGE_NAME=myapp IMAGE_TAG=v1.0.0"; \
		exit 1; \
	fi
	@echo "Building release image: $(IMAGE_NAME):$(IMAGE_TAG)"
	@# Set defaults
	@BUILD_DATE=$${BUILD_DATE:-$$(date -u +'%Y-%m-%dT%H:%M:%SZ')}; \
	PYTHON_BASE=$${PYTHON_BASE:-python:3.12-slim}; \
	\
	docker build \
		--file docker/Dockerfile \
		--tag $(IMAGE_NAME):$(IMAGE_TAG) \
		--build-arg PYTHON_BASE=$$PYTHON_BASE \
		--label "version=$(IMAGE_TAG)" \
		--label "release-date=$$BUILD_DATE" \
		.
	@echo "✓ Release image built successfully: $(IMAGE_NAME):$(IMAGE_TAG)"

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

test_parallel_tests:
	@if [ -z "$(TEST_PATH)" ]; then \
		echo "Error: TEST_PATH not specified"; \
		echo "Usage: make test_parallel_tests TEST_PATH=production/tests/scenarios/ JOBS=4"; \
		exit 1; \
	fi
	@echo "Running tests in parallel: path=$(TEST_PATH), jobs=$(or $(JOBS),4)"
	@docker compose exec -T vt-app poetry run prod parallel tests $(TEST_PATH) --jobs $(or $(JOBS),4)

test_parallel_suites:
	@echo "Running test suite $(or $(COUNT),4) times in parallel..."
	@docker compose exec -T vt-app poetry run prod parallel suites $(or $(SUITE_PATH),production/tests/scenarios/) --count $(or $(COUNT),4)

simulate_test:
	@if [ -z "$(TEST_PATH)" ]; then \
		echo "Error: TEST_PATH not specified"; \
		echo "Usage: make simulate_test TEST_PATH=production/tests/scenarios/allergy_ceph.yaml USERS=10"; \
		exit 1; \
	fi
	@echo "Simulating $(or $(USERS),4) concurrent users running: $(TEST_PATH)"
	@docker compose exec -T vt-app poetry run prod parallel simulate-test $(TEST_PATH) --users $(or $(USERS),4)

simulate_suite:
	@echo "Simulating $(or $(USERS),4) concurrent users running suite: $(or $(SUITE_PATH),production/tests/scenarios/)"
	@docker compose exec -T vt-app poetry run prod parallel simulate-suite $(or $(SUITE_PATH),production/tests/scenarios/) --users $(or $(USERS),4)

calibrate:
	@echo "Running metrics calibration..."
	@docker compose exec -T vt-app poetry run prod calibrate $(ARGS)

generate_report:
	@if [ -z "$(EVAL_ID)" ]; then \
		echo "Error: EVAL_ID not specified"; \
		echo "Usage: make generate_report EVAL_ID=<24-char-hex-objectid>"; \
		echo "Example: make generate_report EVAL_ID=507f1f77bcf86cd799439011"; \
		exit 1; \
	fi
	@echo "Generating PDF report for evaluation: $(EVAL_ID)"
	@docker compose exec -T vt-app poetry run prod generate-report $(EVAL_ID)

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
