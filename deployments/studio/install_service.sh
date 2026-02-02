#!/bin/bash
#
# install_service.sh - Install Monolathe services on Mac Studio
#
# This script installs the MLX Inference Server and Celery Worker as
# launchd services (macOS native service manager).
#
# Usage:
#   cd ~/monolathe/deployments/studio
#   ./install_service.sh
#

set -euo pipefail

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

echo ""
echo "Installing Monolathe services (launchd)..."
echo ""

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$PROJECT_DIR/logs"

install_plist() {
    local template="$1"
    local plist_name="$2"
    local target="$LAUNCH_AGENTS_DIR/$plist_name"

    if [[ ! -f "$template" ]]; then
        log_warn "Template not found: $template"
        return 1
    fi

    sed "s|__MONOLATHE_DIR__|$PROJECT_DIR|g" "$template" > "$target"
    launchctl unload "$target" 2>/dev/null || true
    launchctl load "$target"
    log_ok "Installed: $plist_name"
}

# Install services
install_plist "$SCRIPT_DIR/com.monolathe.mlx.plist.template" "com.monolathe.mlx.plist"
install_plist "$SCRIPT_DIR/com.monolathe.worker.plist.template" "com.monolathe.worker.plist"

echo ""
echo "Services installed. Check status with:"
echo "  launchctl list | grep monolathe"
echo ""
echo "View logs:"
echo "  tail -f $PROJECT_DIR/logs/mlx_server.err.log"
echo "  tail -f $PROJECT_DIR/logs/worker.err.log"
echo ""
