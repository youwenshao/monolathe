# Monolathe Makefile
PYTHON = /opt/homebrew/bin/python3
VENV = .venv
VENV_PYTHON = $(VENV)/bin/python
VENV_PIP = $(VENV_PYTHON) -m pip

.PHONY: help install dev test lint format migrate deploy-studio deploy-mini clean venv

# Default target
help:
	@echo "Monolathe - AI Content Automation Pipeline"
	@echo ""
	@echo "Available targets:"
	@echo "  install       Install dependencies in a virtual environment"
	@echo "  venv          Create virtual environment"
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

# Virtual Environment
venv:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip

# Installation
install: venv
	$(VENV_PIP) install -e .
	$(VENV_PYTHON) -m pre_commit install

# Development
dev:
	$(VENV_PYTHON) -m uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Testing
test:
	$(VENV_PYTHON) -m pytest tests/unit -v

test-int:
	$(VENV_PYTHON) -m pytest tests/integration -v

test-e2e:
	$(VENV_PYTHON) -m pytest tests/e2e -v

test-cov:
	$(VENV_PYTHON) -m pytest --cov=src --cov-report=html --cov-report=term-missing

test-all:
	$(VENV_PYTHON) -m pytest -v --cov=src --cov-report=term-missing

# Linting and formatting
lint:
	$(VENV_PYTHON) -m ruff check src tests
	$(VENV_PYTHON) -m mypy src --strict

format:
	$(VENV_PYTHON) -m black src tests
	$(VENV_PYTHON) -m ruff check --fix src tests

# Database migrations
migrate:
	$(VENV_PYTHON) -m alembic upgrade head

migrate-make:
	@read -p "Migration message: " msg; \
	$(VENV_PYTHON) -m alembic revision --autogenerate -m "$$msg"

migrate-down:
	$(VENV_PYTHON) -m alembic downgrade -1

# Deployment
deploy-mini:
	@echo "Deploying to Mac mini..."
	/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose -f docker-compose.yml up -d --build

deploy-studio:
	@echo "Deploying workers to Mac Studio..."
	scp -r src deployments/studio/ studio.local:~/monolathe/
	ssh studio.local "cd ~/monolathe && ./install_service.sh"

# Docker commands
docker-up:
	/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose up -d

docker-down:
	/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose down

docker-logs:
	/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose logs -f

docker-build:
	/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose build --no-cache

# Celery commands (for local development)
celery-worker:
	$(VENV_PYTHON) -m celery -A src.celery_app worker --loglevel=info --concurrency=2

celery-beat:
	$(VENV_PYTHON) -m celery -A src.celery_app beat --loglevel=info

celery-flower:
	$(VENV_PYTHON) -m celery -A src.celery_app flower --port=5555

# Cleaning
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/ .mypy_cache/ $(VENV) 2>/dev/null || true

# Database
db-init:
	mkdir -p data
	$(VENV_PYTHON) -c "import asyncio; from src.shared.database import init_db; asyncio.run(init_db())"

db-reset:
	 rm -f data/*.db
	$(MAKE) db-init

# Utilities
requirements:
	$(VENV_PIP) install pip-tools
	$(VENV_PYTHON) -m piptools compile pyproject.toml -o requirements.txt
	$(VENV_PYTHON) -m piptools compile --extra dev pyproject.toml -o requirements-dev.txt

seed:
	$(VENV_PYTHON) scripts/seed_data.py

# Health check
health:
	curl -s http://localhost:8000/health | $(VENV_PYTHON) -m json.tool

# Version
version:
	@$(VENV_PYTHON) -c "from src import __version__; print(__version__)"
