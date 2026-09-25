.PHONY: dev up down test lint migrate

dev:
	docker compose up --build
up:
	docker compose up -d --build
down:
	docker compose down
test:
	docker compose run --rm api pytest
lint:
	docker compose run --rm api ruff check .
	docker compose run --rm web npm run lint
migrate:
	docker compose run --rm api alembic upgrade head
