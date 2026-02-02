"""Job monitoring API endpoints."""

from typing import Any
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from src.celery_app import celery_app
from src.shared.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

class JobStatusResponse(BaseModel):
    """Job status response."""
    job_id: str
    status: str
    result: Any | None = None
    error: str | None = None

@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    summary="Get background job status",
)
async def get_job_status(job_id: str) -> JobStatusResponse:
    """Check the status of a Celery background task."""
    try:
        result = celery_app.AsyncResult(job_id)
        
        response = JobStatusResponse(
            job_id=job_id,
            status=result.status,
        )
        
        if result.ready():
            if result.successful():
                response.result = result.result
            else:
                response.error = str(result.result)
                
        return response
    except Exception as e:
        logger.error(f"Failed to fetch job status for {job_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch job status: {str(e)}",
        )
