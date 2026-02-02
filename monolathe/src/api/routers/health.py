"""Health check endpoints."""

import time
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel

from src.shared.config import get_settings
from src.shared.logger import get_logger
from src.shared.redis_client import RedisClient

logger = get_logger(__name__)
router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    version: str
    timestamp: datetime
    checks: dict[str, bool]


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check endpoint",
)
async def health_check() -> HealthResponse:
    """Check API health status."""
    checks: dict[str, bool] = {}
    
    # Check Redis
    try:
        redis = RedisClient()
        await redis.connect()
        await redis.client.ping()
        checks["redis"] = True
        await redis.disconnect()
    except Exception as e:
        logger.warning(f"Redis health check failed: {e}")
        checks["redis"] = False
    
    # Check settings
    try:
        settings = get_settings()
        checks["config"] = bool(settings.secret_key)
    except Exception as e:
        logger.warning(f"Config health check failed: {e}")
        checks["config"] = False
    
    # Overall status
    all_healthy = all(checks.values())
    
    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        version="0.1.0",
        timestamp=datetime.utcnow(),
        checks=checks,
    )


@router.get(
    "/ready",
    status_code=status.HTTP_200_OK,
    summary="Readiness probe",
)
async def readiness_check() -> dict[str, str]:
    """Kubernetes-style readiness probe."""
    return {"status": "ready"}


@router.get(
    "/live",
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
)
async def liveness_check() -> dict[str, str]:
    """Kubernetes-style liveness probe."""
    return {"status": "alive"}
