#!/bin/bash
#
# setup_studio.sh - Quickstart setup for Mac Studio (MLX Inference Node)
#
# This script sets up the Mac Studio as the AI inference server for
# the Monolathe pipeline. It runs:
#   - MLX Inference Server (F5-TTS, FLUX, CogVideoX)
#   - Celery Worker (mlx_inference queue)
#
# Prerequisites:
#   - macOS with Homebrew installed
#   - Python 3.12+ installed
#   - Mac mini running and accessible at mini.local
#   - Shared storage mounted at /Volumes/ai_content_shared (optional)
#
# Usage:
#   ./scripts/setup_studio.sh
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

# Configuration
MINI_HOST="${MINI_HOST:-mini.local}"
REDIS_URL="${REDIS_URL:-redis://${MINI_HOST}:6379/0}"

echo ""
echo "========================================"
echo "  Monolathe - Mac Studio Setup"
echo "  (MLX Inference Node)"
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

# Check Apple Silicon
if [[ "$(uname -m)" != "arm64" ]]; then
    log_error "This script requires Apple Silicon (arm64). Found: $(uname -m)"
    exit 1
fi
log_ok "Apple Silicon detected"

# -----------------------------------------------------------------------------
# Step 2: Check connectivity to Mac mini
# -----------------------------------------------------------------------------
log_info "Checking connectivity to Mac mini ($MINI_HOST)..."

if ! ping -c 1 -W 2 "$MINI_HOST" &> /dev/null; then
    log_warn "Cannot reach $MINI_HOST. Make sure:"
    echo "  1. Mac mini is running and on the same network"
    echo "  2. Hostname is configured (or set MINI_HOST=<ip-address>)"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    log_ok "Mac mini is reachable"
fi

# Check Redis connectivity
if command -v redis-cli &> /dev/null; then
    if redis-cli -h "$MINI_HOST" -p 6379 ping 2>/dev/null | grep -q "PONG"; then
        log_ok "Redis on Mac mini is accessible"
    else
        log_warn "Cannot connect to Redis on $MINI_HOST:6379"
        log_warn "Make sure Docker services are running on the Mac mini"
    fi
else
    log_info "redis-cli not installed, skipping Redis connectivity check"
fi

# -----------------------------------------------------------------------------
# Step 3: Create Python virtual environment
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
# Step 4: Install Python dependencies
# -----------------------------------------------------------------------------
log_info "Installing Python dependencies..."

pip install -e "." -q
log_ok "Core dependencies installed"

# Install MLX dependencies
log_info "Installing MLX dependencies..."
pip install mlx mlx-lm -q 2>/dev/null || {
    log_warn "MLX installation may have issues - continuing anyway"
}
log_ok "MLX dependencies installed"

# Install uvicorn and celery explicitly
pip install uvicorn celery -q
log_ok "uvicorn and celery installed"

# -----------------------------------------------------------------------------
# Step 5: Setup environment file
# -----------------------------------------------------------------------------
log_info "Checking environment configuration..."

if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
        cp .env.example .env
        # Update REDIS_URL to point to Mac mini
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s|REDIS_URL=.*|REDIS_URL=${REDIS_URL}|g" .env
        else
            sed -i "s|REDIS_URL=.*|REDIS_URL=${REDIS_URL}|g" .env
        fi
        log_warn ".env file created from .env.example"
        log_warn "REDIS_URL updated to point to $MINI_HOST"
    else
        log_error "No .env.example file found. Please create a .env file."
        exit 1
    fi
else
    log_ok ".env file exists"
fi

# -----------------------------------------------------------------------------
# Step 6: Create logs directory
# -----------------------------------------------------------------------------
log_info "Creating logs directory..."
mkdir -p "$PROJECT_DIR/logs"
log_ok "Logs directory ready"

# -----------------------------------------------------------------------------
# Step 7: Install launchd services
# -----------------------------------------------------------------------------
log_info "Installing launchd services..."

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS_DIR"

TEMPLATE_DIR="$PROJECT_DIR/deployments/studio"

# Function to install a plist from template
install_plist() {
    local template="$1"
    local plist_name="$2"
    local target="$LAUNCH_AGENTS_DIR/$plist_name"

    if [[ ! -f "$template" ]]; then
        log_error "Template not found: $template"
        return 1
    fi

    # Replace placeholder with actual project directory
    sed "s|__MONOLATHE_DIR__|$PROJECT_DIR|g" "$template" > "$target"

    # Unload if already loaded
    launchctl unload "$target" 2>/dev/null || true

    # Load the service
    launchctl load "$target"

    log_ok "Installed and loaded: $plist_name"
}

# Install MLX Server
if [[ -f "$TEMPLATE_DIR/com.monolathe.mlx.plist.template" ]]; then
    install_plist "$TEMPLATE_DIR/com.monolathe.mlx.plist.template" "com.monolathe.mlx.plist"
else
    log_warn "MLX plist template not found, skipping"
fi

# Install Celery Worker
if [[ -f "$TEMPLATE_DIR/com.monolathe.worker.plist.template" ]]; then
    install_plist "$TEMPLATE_DIR/com.monolathe.worker.plist.template" "com.monolathe.worker.plist"
else
    log_warn "Worker plist template not found, skipping"
fi

# -----------------------------------------------------------------------------
# Step 8: Verify services
# -----------------------------------------------------------------------------
log_info "Verifying services..."
sleep 3

# Check MLX Server
MLX_RUNNING=false
for i in {1..10}; do
    if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
        MLX_RUNNING=true
        break
    fi
    sleep 2
done

if $MLX_RUNNING; then
    log_ok "MLX Inference Server is healthy"
else
    log_warn "MLX Server not responding yet. Check logs:"
    echo "  tail -f $PROJECT_DIR/logs/mlx_server.err.log"
fi

# Check launchd status
if launchctl list | grep -q "com.monolathe.mlx"; then
    log_ok "MLX service is registered with launchd"
else
    log_warn "MLX service may not be running"
fi

if launchctl list | grep -q "com.monolathe.worker"; then
    log_ok "Worker service is registered with launchd"
else
    log_warn "Worker service may not be running"
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
echo "========================================"
echo "  Setup Complete!"
echo "========================================"
echo ""
echo "Services installed:"
echo "  - MLX Inference Server: http://localhost:8080"
echo "  - Celery Worker:        Listening on mlx_inference queue"
echo ""
echo "Service management commands:"
echo "  # View service status"
echo "  launchctl list | grep monolathe"
echo ""
echo "  # Stop services"
echo "  launchctl unload ~/Library/LaunchAgents/com.monolathe.mlx.plist"
echo "  launchctl unload ~/Library/LaunchAgents/com.monolathe.worker.plist"
echo ""
echo "  # Start services"
echo "  launchctl load ~/Library/LaunchAgents/com.monolathe.mlx.plist"
echo "  launchctl load ~/Library/LaunchAgents/com.monolathe.worker.plist"
echo ""
echo "  # View logs"
echo "  tail -f $PROJECT_DIR/logs/mlx_server.out.log"
echo "  tail -f $PROJECT_DIR/logs/mlx_server.err.log"
echo "  tail -f $PROJECT_DIR/logs/worker.out.log"
echo ""
echo "Health check:"
echo "  curl http://localhost:8080/health"
echo ""
