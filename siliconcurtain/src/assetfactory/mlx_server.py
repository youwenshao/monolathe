"""MLX Inference Server for Mac Studio M4 Max.

Provides FastAPI endpoints for local AI generation using MLX framework.
Optimized for 48GB unified memory with semaphore-based resource management.
"""

import asyncio
import gc
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psutil
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.shared.config import get_settings
from src.shared.logger import get_logger
from src.shared.models_reels import GenerationJob, GenerationMetrics

logger = get_logger(__name__)
app = FastAPI(title="MLX Inference Server", version="0.2.0")

# Resource management
_settings = get_settings()
_video_semaphore = asyncio.Semaphore(_settings.max_concurrent_video_gens)
_image_semaphore = asyncio.Semaphore(_settings.max_concurrent_image_gens)
_voice_semaphore = asyncio.Semaphore(4)  # F5-TTS can run more concurrently

# Job tracking
_active_jobs: dict[str, GenerationJob] = {}
_job_metrics: dict[str, GenerationMetrics] = {}


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str = "0.2.0"
    vram_used_gb: float
    vram_available_gb: float
    cpu_percent: float
    active_jobs: int
    queue_depth: int


class VoiceGenerationRequest(BaseModel):
    """F5-TTS voice generation request."""
    text: str = Field(..., min_length=10, max_length=5000)
    voice_reference_path: str | None = None
    emotion: str = Field(default="neutral", pattern="^(neutral|excited|calm|urgent)$")
    speed: float = Field(default=1.0, ge=0.8, le=1.5)
    output_format: str = Field(default="wav", pattern="^(wav|mp3|aac)$")


class VoiceGenerationResponse(BaseModel):
    """Voice generation response."""
    job_id: str
    status: str
    audio_path: str | None = None
    duration_seconds: float | None = None
    estimated_time: float


class ImageGenerationRequest(BaseModel):
    """FLUX-dev image generation request."""
    prompt: str = Field(..., min_length=10, max_length=1000)
    negative_prompt: str = Field(default="")
    width: int = Field(default=1080, ge=512, le=1920)
    height: int = Field(default=1920, ge=512, le=1920)
    steps: int = Field(default=20, ge=10, le=50)
    cfg_scale: float = Field(default=3.5, ge=1.0, le=20.0)
    lora_name: str | None = None
    seed: int | None = None


class ImageGenerationResponse(BaseModel):
    """Image generation response."""
    job_id: str
    status: str
    image_path: str | None = None
    generation_time: float | None = None


class VideoGenerationRequest(BaseModel):
    """CogVideoX video generation request."""
    image_path: str
    motion_prompt: str = Field(default="subtle camera movement, natural motion")
    duration_seconds: float = Field(default=6.0, ge=3.0, le=10.0)
    fps: int = Field(default=8, ge=8, le=24)
    interpolation: bool = True


class VideoGenerationResponse(BaseModel):
    """Video generation response."""
    job_id: str
    status: str
    video_path: str | None = None
    generation_time: float | None = None


def get_vram_usage() -> tuple[float, float]:
    """Get current VRAM usage in GB.
    
    Returns:
        Tuple of (used_gb, available_gb)
    """
    try:
        import mlx.core as mx
        # MLX uses unified memory, get from system
        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024 ** 3)
        available_gb = mem.available / (1024 ** 3)
        used_gb = total_gb - available_gb
        return used_gb, available_gb
    except ImportError:
        # Fallback if MLX not available
        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024 ** 3)
        available_gb = mem.available / (1024 ** 3)
        return total_gb - available_gb, available_gb


def check_resource_availability(required_gb: float = 4.0) -> bool:
    """Check if sufficient VRAM is available.
    
    Args:
        required_gb: Required VRAM in GB
        
    Returns:
        True if resources available
    """
    used, available = get_vram_usage()
    return available >= required_gb


async def generate_voice_task(
    job_id: str,
    request: VoiceGenerationRequest,
) -> None:
    """Background task for voice generation.
    
    Args:
        job_id: Generation job ID
        request: Voice generation parameters
    """
    start_time = time.time()
    vram_before = get_vram_usage()[0]
    
    try:
        job = _active_jobs.get(job_id)
        if job:
            job.status = "running"
            job.started_at = time.time()
        
        logger.info(f"Starting voice generation job {job_id}")
        
        # TODO: Implement actual F5-TTS inference
        # Placeholder for implementation:
        # 1. Load F5-TTS model
        # 2. Process text
        # 3. Generate audio with emotion/speed controls
        # 4. Save to shared storage
        
        await asyncio.sleep(2)  # Simulate generation
        
        output_path = f"/Volumes/ai_content_shared/audio/{job_id}.wav"
        
        # Calculate metrics
        generation_time = time.time() - start_time
        vram_after = get_vram_usage()[0]
        
        if job:
            job.status = "completed"
            job.completed_at = time.time()
            job.output_path = output_path
            job.metrics = {
                "generation_time": generation_time,
                "vram_peak": vram_after,
                "text_length": len(request.text),
            }
        
        _job_metrics[job_id] = GenerationMetrics(
            job_id=job_id,
            job_type="voice",
            duration_seconds=generation_time,
            vram_peak_gb=vram_after,
            cpu_percent=psutil.cpu_percent(),
        )
        
        logger.info(f"Voice generation completed: {job_id} in {generation_time:.2f}s")
        
    except Exception as e:
        logger.error(f"Voice generation failed: {e}")
        if job_id in _active_jobs:
            _active_jobs[job_id].status = "failed"
            _active_jobs[job_id].error_message = str(e)
        raise
    finally:
        # Force garbage collection
        gc.collect()


async def generate_image_task(
    job_id: str,
    request: ImageGenerationRequest,
) -> None:
    """Background task for image generation.
    
    Args:
        job_id: Generation job ID
        request: Image generation parameters
    """
    start_time = time.time()
    
    try:
        job = _active_jobs.get(job_id)
        if job:
            job.status = "running"
            job.started_at = time.time()
        
        logger.info(f"Starting image generation job {job_id}: {request.prompt[:50]}...")
        
        # Check VRAM
        if not check_resource_availability(required_gb=8.0):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Insufficient VRAM available",
            )
        
        # TODO: Implement actual FLUX-dev GGUF inference
        # Placeholder for implementation:
        # 1. Load FLUX model with mlx-lm
        # 2. Apply LoRA if specified
        # 3. Generate with specified params
        # 4. Save to shared storage
        
        await asyncio.sleep(5)  # Simulate generation
        
        output_path = f"/Volumes/ai_content_shared/images/{job_id}.png"
        
        generation_time = time.time() - start_time
        vram_used = get_vram_usage()[0]
        
        if job:
            job.status = "completed"
            job.completed_at = time.time()
            job.output_path = output_path
            job.metrics = {
                "generation_time": generation_time,
                "resolution": f"{request.width}x{request.height}",
                "steps": request.steps,
            }
        
        _job_metrics[job_id] = GenerationMetrics(
            job_id=job_id,
            job_type="image",
            duration_seconds=generation_time,
            vram_peak_gb=vram_used,
            cpu_percent=psutil.cpu_percent(),
        )
        
        logger.info(f"Image generation completed: {job_id} in {generation_time:.2f}s")
        
    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        if job_id in _active_jobs:
            _active_jobs[job_id].status = "failed"
            _active_jobs[job_id].error_message = str(e)
        raise
    finally:
        gc.collect()


async def generate_video_task(
    job_id: str,
    request: VideoGenerationRequest,
) -> None:
    """Background task for video generation.
    
    Args:
        job_id: Generation job ID
        request: Video generation parameters
    """
    start_time = time.time()
    
    try:
        job = _active_jobs.get(job_id)
        if job:
            job.status = "running"
            job.started_at = time.time()
        
        logger.info(f"Starting video generation job {job_id}")
        
        # Check VRAM - video gen needs more
        if not check_resource_availability(required_gb=16.0):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Insufficient VRAM for video generation",
            )
        
        # TODO: Implement actual CogVideoX-I2V inference
        # Placeholder for implementation:
        # 1. Load CogVideoX model
        # 2. Process input image
        # 3. Generate video frames
        # 4. Apply RIFE interpolation if requested
        # 5. Encode to H.264
        # 6. Save to shared storage
        
        await asyncio.sleep(15)  # Simulate generation
        
        output_path = f"/Volumes/ai_content_shared/videos/{job_id}.mp4"
        
        generation_time = time.time() - start_time
        vram_used = get_vram_usage()[0]
        
        if job:
            job.status = "completed"
            job.completed_at = time.time()
            job.output_path = output_path
            job.metrics = {
                "generation_time": generation_time,
                "duration": request.duration_seconds,
                "fps": request.fps,
            }
        
        _job_metrics[job_id] = GenerationMetrics(
            job_id=job_id,
            job_type="video",
            duration_seconds=generation_time,
            vram_peak_gb=vram_used,
            cpu_percent=psutil.cpu_percent(),
        )
        
        logger.info(f"Video generation completed: {job_id} in {generation_time:.2f}s")
        
    except Exception as e:
        logger.error(f"Video generation failed: {e}")
        if job_id in _active_jobs:
            _active_jobs[job_id].status = "failed"
            _active_jobs[job_id].error_message = str(e)
        raise
    finally:
        gc.collect()


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    used, available = get_vram_usage()
    
    return HealthResponse(
        status="healthy" if available > 4.0 else "degraded",
        vram_used_gb=round(used, 2),
        vram_available_gb=round(available, 2),
        cpu_percent=psutil.cpu_percent(interval=0.1),
        active_jobs=len([j for j in _active_jobs.values() if j.status == "running"]),
        queue_depth=len([j for j in _active_jobs.values() if j.status == "pending"]),
    )


@app.post("/generate/voice", response_model=VoiceGenerationResponse)
async def generate_voice(
    request: VoiceGenerationRequest,
    background_tasks: BackgroundTasks,
) -> VoiceGenerationResponse:
    """Generate voiceover using F5-TTS.
    
    Args:
        request: Voice generation parameters
        background_tasks: FastAPI background tasks
        
    Returns:
        Job information and estimated completion time
    """
    job_id = f"voice_{int(time.time() * 1000)}"
    
    # Create job tracking
    job = GenerationJob(
        content_id=job_id,
        job_type="voice",
        status="pending",
        priority=5,
    )
    _active_jobs[job_id] = job
    
    # Estimate time based on text length (~2s per 100 chars)
    estimated_time = max(5, len(request.text) / 50)
    
    # Start background task with semaphore
    async with _voice_semaphore:
        background_tasks.add_task(generate_voice_task, job_id, request)
    
    return VoiceGenerationResponse(
        job_id=job_id,
        status="pending",
        estimated_time=estimated_time,
    )


@app.post("/generate/image", response_model=ImageGenerationResponse)
async def generate_image(
    request: ImageGenerationRequest,
    background_tasks: BackgroundTasks,
) -> ImageGenerationResponse:
    """Generate image using FLUX-dev.
    
    Args:
        request: Image generation parameters
        background_tasks: FastAPI background tasks
        
    Returns:
        Job information
    """
    job_id = f"img_{int(time.time() * 1000)}"
    
    job = GenerationJob(
        content_id=job_id,
        job_type="image",
        status="pending",
        priority=5,
    )
    _active_jobs[job_id] = job
    
    # Check aspect ratio for Reels
    aspect = request.width / request.height
    if not (0.5 <= aspect <= 0.6):  # 9:16 is 0.5625
        logger.warning(f"Non-optimal aspect ratio: {aspect:.3f}, expected ~0.56 for Reels")
    
    async with _image_semaphore:
        background_tasks.add_task(generate_image_task, job_id, request)
    
    return ImageGenerationResponse(
        job_id=job_id,
        status="pending",
    )


@app.post("/generate/video", response_model=VideoGenerationResponse)
async def generate_video(
    request: VideoGenerationRequest,
    background_tasks: BackgroundTasks,
) -> VideoGenerationResponse:
    """Generate video using CogVideoX.
    
    Args:
        request: Video generation parameters
        background_tasks: FastAPI background tasks
        
    Returns:
        Job information
    """
    job_id = f"vid_{int(time.time() * 1000)}"
    
    job = GenerationJob(
        content_id=job_id,
        job_type="video",
        status="pending",
        priority=5,
    )
    _active_jobs[job_id] = job
    
    async with _video_semaphore:
        background_tasks.add_task(generate_video_task, job_id, request)
    
    return VideoGenerationResponse(
        job_id=job_id,
        status="pending",
    )


@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str) -> dict[str, Any]:
    """Get job status and metrics.
    
    Args:
        job_id: Job identifier
        
    Returns:
        Job status, output path, and metrics
    """
    if job_id not in _active_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    
    job = _active_jobs[job_id]
    metrics = _job_metrics.get(job_id)
    
    return {
        "job_id": job_id,
        "status": job.status,
        "job_type": job.job_type,
        "output_path": job.output_path,
        "created_at": job.created_at.isoformat() if hasattr(job.created_at, 'isoformat') else job.created_at,
        "metrics": job.metrics,
        "performance": metrics.model_dump() if metrics else None,
    }


@app.get("/jobs")
async def list_jobs(
    status: str | None = None,
    job_type: str | None = None,
) -> list[dict[str, Any]]:
    """List all jobs with optional filtering.
    
    Args:
        status: Filter by status
        job_type: Filter by job type
        
    Returns:
        List of job information
    """
    jobs = _active_jobs.values()
    
    if status:
        jobs = [j for j in jobs if j.status == status]
    if job_type:
        jobs = [j for j in jobs if j.job_type == job_type]
    
    return [
        {
            "job_id": j.id,
            "status": j.status,
            "job_type": j.job_type,
            "created_at": j.created_at,
        }
        for j in jobs
    ]


@app.get("/metrics")
async def get_metrics() -> dict[str, Any]:
    """Get aggregate performance metrics."""
    if not _job_metrics:
        return {"message": "No metrics available yet"}
    
    metrics_list = list(_job_metrics.values())
    
    by_type: dict[str, list[GenerationMetrics]] = {}
    for m in metrics_list:
        by_type.setdefault(m.job_type, []).append(m)
    
    return {
        "total_jobs": len(metrics_list),
        "by_type": {
            job_type: {
                "count": len(type_metrics),
                "avg_duration": sum(m.duration_seconds for m in type_metrics) / len(type_metrics),
                "avg_vram": sum(m.vram_peak_gb for m in type_metrics) / len(type_metrics),
                "avg_efficiency": sum(m.efficiency_score for m in type_metrics) / len(type_metrics),
            }
            for job_type, type_metrics in by_type.items()
        },
        "system": {
            "vram_used_gb": get_vram_usage()[0],
            "vram_available_gb": get_vram_usage()[1],
            "cpu_percent": psutil.cpu_percent(),
        },
    }


@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str) -> dict[str, str]:
    """Cancel a pending or running job.
    
    Args:
        job_id: Job to cancel
        
    Returns:
        Cancellation confirmation
    """
    if job_id not in _active_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    
    job = _active_jobs[job_id]
    if job.status in ["completed", "failed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel completed job",
        )
    
    job.status = "cancelled"
    return {"message": f"Job {job_id} cancelled"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
