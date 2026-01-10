COMPOSE = docker compose -f docker-compose.yml

.PHONY: docker-build docker-run docker-run-detached docker-logs docker-stop docker-clean


docker-build:
	$(COMPOSE) build

docker-run:
	$(COMPOSE) up

docker-run-detached:
	$(COMPOSE) up -d

docker-logs:
	$(COMPOSE) logs -f

docker-stop:
	$(COMPOSE) down

docker-clean:
	$(COMPOSE) down --rmi local --remove-orphans
