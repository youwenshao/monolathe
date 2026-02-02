# Monolathe Makefile
.PHONY: help install dev test lint format migrate deploy-studio deploy-mini clean

# Default target
help:
	@echo "Monolathe - AI Content Automation Pipeline"
	@echo ""
	@echo "Available targets:"
	@echo "  install       Install dependencies"
	@echo "  dev           Run in development mode"
	@echo "  test          Run test suite"
	@echo "  test-cov      Run tests with coverage"
	@echo "  lint          Run linters (ruff, mypy)"
	@echo "  format        Format code (black, ruff)"
	@echo "  migrate       Run database migrations"
	@echo "  migrate-make  Create new migration"
	@echo "  deploy-mini   Deploy to Mac mini"
	@echo "  deploy-studio Deploy workers to Mac Studio"
	@echo "  docker-up     Start Docker Compose services"
	@echo "  docker-down   Stop Docker Compose services"
	@echo "  clean         Clean temporary files"

# Installation
install:
	pip install -e ".[dev]"
	pre-commit install

# Development
dev:
	uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Testing
test:
	pytest tests/unit -v

test-int:
	pytest tests/integration -v

test-e2e:
	pytest tests/e2e -v

test-cov:
	pytest --cov=src --cov-report=html --cov-report=term-missing

test-all:
	pytest -v --cov=src --cov-report=term-missing

# Linting and formatting
lint:
	ruff check src tests
	mypy src --strict

format:
	black src tests
	ruff check --fix src tests

# Database migrations
migrate:
	alembic upgrade head

migrate-make:
	@read -p "Migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

migrate-down:
	alembic downgrade -1

# Deployment
deploy-mini:
	@echo "Deploying to Mac mini..."
	docker-compose -f docker-compose.yml up -d --build

deploy-studio:
	@echo "Deploying workers to Mac Studio..."
	scp -r src deployments/studio/ studio.local:~/monolathe/
	ssh studio.local "cd ~/monolathe && ./install_service.sh"

# Docker commands
docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-build:
	docker-compose build --no-cache

# Celery commands (for local development)
celery-worker:
	celery -A src.celery_app worker --loglevel=info --concurrency=2

celery-beat:
	celery -A src.celery_app beat --loglevel=info

celery-flower:
	celery -A src.celery_app flower --port=5555

# Cleaning
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/ .mypy_cache/ 2>/dev/null || true

# Database
db-init:
	mkdir -p data
	python -c "import asyncio; from src.shared.database import init_db; asyncio.run(init_db())"

db-reset:
	 rm -f data/*.db
	$(MAKE) db-init

# Utilities
requirements:
	pip-compile pyproject.toml -o requirements.txt
	pip-compile --extra dev pyproject.toml -o requirements-dev.txt

seed:
	python scripts/seed_data.py

# Health check
health:
	curl -s http://localhost:8000/health | python -m json.tool

# Version
version:
	@python -c "from src import __version__; print(__version__)"
