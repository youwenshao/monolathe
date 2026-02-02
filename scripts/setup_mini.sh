#!/bin/bash
#
# setup_mini.sh - Quickstart setup for Mac mini (Orchestration Node)
#
# This script sets up the Mac mini as the orchestration controller for
# the Monolathe pipeline. It runs:
#   - Redis (message broker)
#   - FastAPI (API server)
#   - Celery workers (background tasks)
#   - Celery beat (scheduler)
#
# Prerequisites:
#   - macOS with Homebrew installed
#   - Docker Desktop installed and running
#   - Python 3.12+ installed via Homebrew
#
# Usage:
#   ./scripts/setup_mini.sh
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo ""
echo "========================================"
echo "  Monolathe - Mac mini Setup"
echo "  (Orchestration Node)"
echo "========================================"
echo ""

cd "$PROJECT_DIR"
log_info "Working directory: $PROJECT_DIR"

# -----------------------------------------------------------------------------
# Step 1: Check prerequisites
# -----------------------------------------------------------------------------
log_info "Checking prerequisites..."

# Check for Homebrew
if ! command -v brew &> /dev/null; then
    log_error "Homebrew is not installed. Please install it first:"
    echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi
log_ok "Homebrew found"

# Check for Python 3.12+
if ! command -v python3 &> /dev/null; then
    log_error "Python 3 is not installed. Installing via Homebrew..."
    brew install python@3.12
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 12 ]]; then
    log_error "Python 3.12+ is required. Found: Python $PYTHON_VERSION"
    log_info "Installing Python 3.12 via Homebrew..."
    brew install python@3.12
fi
log_ok "Python $PYTHON_VERSION found"

# Check for Docker
if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed. Please install Docker Desktop from:"
    echo "  https://www.docker.com/products/docker-desktop/"
    exit 1
fi

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    log_error "Docker daemon is not running. Please start Docker Desktop."
    exit 1
fi
log_ok "Docker is running"

# Check for docker compose (V2)
if ! docker compose version &> /dev/null; then
    log_error "Docker Compose V2 is not available."
    log_info "Please ensure Docker Desktop is up to date."
    exit 1
fi
log_ok "Docker Compose V2 found"

# -----------------------------------------------------------------------------
# Step 2: Create Python virtual environment
# -----------------------------------------------------------------------------
log_info "Setting up Python virtual environment..."

if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
    log_ok "Virtual environment created"
else
    log_ok "Virtual environment already exists"
fi

# Activate venv
source .venv/bin/activate
log_ok "Virtual environment activated"

# Upgrade pip
pip install --upgrade pip -q
log_ok "pip upgraded"

# -----------------------------------------------------------------------------
# Step 3: Install Python dependencies
# -----------------------------------------------------------------------------
log_info "Installing Python dependencies..."

pip install -e "." -q
log_ok "Dependencies installed"

# Install pre-commit hooks if available
if [[ -f ".pre-commit-config.yaml" ]]; then
    pip install pre-commit -q
    pre-commit install -q 2>/dev/null || true
    log_ok "Pre-commit hooks installed"
fi

# -----------------------------------------------------------------------------
# Step 4: Setup environment file
# -----------------------------------------------------------------------------
log_info "Checking environment configuration..."

if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
        cp .env.example .env
        log_warn ".env file created from .env.example"
        log_warn "Please edit .env with your API keys before running the pipeline!"
    else
        log_error "No .env.example file found. Please create a .env file."
        exit 1
    fi
else
    log_ok ".env file exists"
fi

# -----------------------------------------------------------------------------
# Step 5: Initialize database
# -----------------------------------------------------------------------------
log_info "Initializing database..."

mkdir -p data
python -c "import asyncio; from src.shared.database import init_db; asyncio.run(init_db())" 2>/dev/null || {
    log_warn "Database initialization skipped (may already exist or module not ready)"
}
log_ok "Database directory ready"

# Run migrations if alembic is configured
if [[ -f "alembic.ini" ]]; then
    log_info "Running database migrations..."
    python -m alembic upgrade head 2>/dev/null || {
        log_warn "Migrations skipped (may need configuration)"
    }
fi

# -----------------------------------------------------------------------------
# Step 6: Start Docker services
# -----------------------------------------------------------------------------
log_info "Starting Docker services..."

docker compose -f docker-compose.yml up -d --build

# Wait for services to be healthy
log_info "Waiting for services to start..."
sleep 5

# Check if services are running
if docker compose ps | grep -q "Up"; then
    log_ok "Docker services started"
else
    log_error "Some Docker services failed to start. Check logs with:"
    echo "  docker compose logs"
    exit 1
fi

# -----------------------------------------------------------------------------
# Step 7: Verify deployment
# -----------------------------------------------------------------------------
log_info "Verifying deployment..."

# Check Redis
if docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q "PONG"; then
    log_ok "Redis is healthy"
else
    log_warn "Redis health check failed (may still be starting)"
fi

# Check API (with retries)
API_READY=false
for i in {1..10}; do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        API_READY=true
        break
    fi
    sleep 2
done

if $API_READY; then
    log_ok "API is healthy"
else
    log_warn "API health check failed. Check logs with: docker compose logs api"
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
echo "========================================"
echo "  Setup Complete!"
echo "========================================"
echo ""
echo "Services running:"
echo "  - API:       http://localhost:8000"
echo "  - Redis:     localhost:6379"
echo "  - Health:    http://localhost:8000/health"
echo ""
echo "Useful commands:"
echo "  docker compose logs -f      # View logs"
echo "  docker compose ps           # Check status"
echo "  docker compose down         # Stop services"
echo "  docker compose restart      # Restart services"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys (if not done)"
echo "  2. Run setup_studio.sh on the Mac Studio"
echo "  3. Verify connectivity: curl http://localhost:8000/health"
echo ""
