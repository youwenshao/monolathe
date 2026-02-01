#!/bin/bash
# Install systemd service for Mac Studio Celery worker

set -e

echo "Installing SiliconCurtain Celery Worker service..."

# Copy service file
sudo cp celery_worker.service /etc/systemd/system/siliconcurtain-worker.service

# Reload systemd
sudo systemctl daemon-reload

# Enable and start service
sudo systemctl enable siliconcurtain-worker
sudo systemctl start siliconcurtain-worker

echo "Service installed and started."
echo "Check status with: sudo systemctl status siliconcurtain-worker"
