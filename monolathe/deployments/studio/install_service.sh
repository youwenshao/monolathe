#!/bin/bash
# Install systemd service for Mac Studio Celery worker

set -e

echo "Installing Monolathe Celery Worker service..."

# Copy service file
sudo cp celery_worker.service /etc/systemd/system/monolathe-worker.service

# Reload systemd
sudo systemctl daemon-reload

# Enable and start service
sudo systemctl enable monolathe-worker
sudo systemctl start monolathe-worker

echo "Service installed and started."
echo "Check status with: sudo systemctl status monolathe-worker"
