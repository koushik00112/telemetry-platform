.PHONY: install lint test test-integration up down observability drill load

install:
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev,load]"

lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app simulator

test:
	.venv/bin/pytest --cov=app --cov=simulator --cov-report=term-missing

test-integration:
	docker compose up -d db
	DATABASE_URL=postgresql+psycopg://telemetry:telemetry@localhost:5432/telemetry .venv/bin/pytest -m integration

up:
	docker compose up -d --build api worker

down:
	docker compose --profile observability down

observability:
	docker compose --profile observability up -d --build

drill:
	scripts/db_outage_drill.sh

load:
	mkdir -p loadtest/results
	.venv/bin/locust -f loadtest/locustfile.py --host http://localhost:8000 --headless -u 50 -r 10 -t 3m --csv loadtest/results/u50
