.PHONY: install fe-install fe-build fe-copy run docker-build docker-run

install:
	poetry install

fe-install:
	cd frontend && npm ci

fe-build:
	cd frontend && npm run build

fe-copy:
	mkdir -p src/acs_webclient/web/static
	cp -r frontend/dist/* src/acs_webclient/web/static/

run:
	poetry run uvicorn acs_webclient.main:app --host 0.0.0.0 --port 8000

docker-build:
	docker build -t acs-webclient:latest .

docker-run:
	docker run --rm -p 8000:8000 \
		-e TRANSLATION_WEBSOCKET_URL=$${TRANSLATION_WEBSOCKET_URL:-ws://localhost:8080/ws} \
		acs-webclient:latest
