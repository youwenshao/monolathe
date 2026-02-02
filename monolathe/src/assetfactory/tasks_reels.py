"""Celery tasks for Reels asset generation.

Integrates with MLX Inference Server on Mac Studio for local AI generation.
"""

import asyncio
from typing import Any

import httpx

from src.celery_app import celery_app
from src.shared.config import get_settings
from src.shared.logger import get_logger

logger = get_logger(__name__)

settings = get_settings()
MLX_SERVER_URL = f"http://{settings.studio_host}:8080"


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def generate_voice_reels(
    self,
    script_text: str,
    emotion: str = "neutral",
    speed: float = 1.0,
) -> dict[str, Any]:
    """Generate voiceover for Reels using F5-TTS.
    
    Args:
        script_text: Text to synthesize (should be < 90s when spoken)
        emotion: Voice emotion (neutral, excited, calm, urgent)
        speed: Speech speed multiplier
        
    Returns:
        Audio file path and duration
    """
    try:
        logger.info(f"Generating voice for Reels: {script_text[:50]}...")
        
        # Call MLX Inference Server
        response = httpx.post(
            f"{MLX_SERVER_URL}/generate/voice",
            json={
                "text": script_text,
                "emotion": emotion,
                "speed": speed,
                "output_format": "wav",
            },
            timeout=120.0,
        )
        response.raise_for_status()
        
        result = response.json()
        job_id = result["job_id"]
        
        # Poll for completion
        audio_path = _poll_job_completion(job_id, max_wait=300)
        
        if not audio_path:
            raise self.retry(exc=Exception("Voice generation timeout"))
        
        return {
            "status": "success",
            "audio_path": audio_path,
            "job_id": job_id,
            "emotion": emotion,
            "speed": speed,
        }
        
    except httpx.HTTPStatusError as e:
        logger.error(f"Voice generation API error: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"Voice generation failed: {e}")
        raise self.retry(exc=e)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def generate_background_image(
    self,
    prompt: str,
    content_style: str,
    lora_name: str | None = None,
) -> dict[str, Any]:
    """Generate 9:16 background image using FLUX-dev.
    
    Args:
        prompt: Image generation prompt
        content_style: Style preset (finance, storytelling, tech)
        lora_name: Optional LoRA to apply
        
    Returns:
        Image file path and metadata
    """
    try:
        logger.info(f"Generating 9:16 image: {prompt[:50]}...")
        
        # Style-specific LoRA mapping
        style_loras = {
            "finance": "finance_reels",
            "storytelling": "storytelling_reels",
            "tech": "tech_reels",
            "history": "history_reels",
            "mystery": "mystery_reels",
        }
        
        lora = lora_name or style_loras.get(content_style, "general_reels")
        
        response = httpx.post(
            f"{MLX_SERVER_URL}/generate/image",
            json={
                "prompt": prompt,
                "width": 1080,
                "height": 1920,
                "steps": 20,
                "cfg_scale": 3.5,
                "lora_name": lora,
            },
            timeout=180.0,
        )
        response.raise_for_status()
        
        result = response.json()
        job_id = result["job_id"]
        
        # Poll for completion
        image_path = _poll_job_completion(job_id, max_wait=300)
        
        if not image_path:
            raise self.retry(exc=Exception("Image generation timeout"))
        
        return {
            "status": "success",
            "image_path": image_path,
            "job_id": job_id,
            "resolution": "1080x1920",
            "aspect_ratio": "9:16",
        }
        
    except httpx.HTTPStatusError as e:
        logger.error(f"Image generation API error: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        raise self.retry(exc=e)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def generate_b_roll_clip(
    self,
    image_path: str,
    motion_description: str,
    duration: float = 6.0,
) -> dict[str, Any]:
    """Generate B-roll video clip using CogVideoX.
    
    Args:
        image_path: Source image path (1080x1920)
        motion_description: Motion prompt
        duration: Target duration (3-10s)
        
    Returns:
        Video clip path and metadata
    """
    try:
        logger.info(f"Generating B-roll from: {image_path}")
        
        response = httpx.post(
            f"{MLX_SERVER_URL}/generate/video",
            json={
                "image_path": image_path,
                "motion_prompt": motion_description,
                "duration_seconds": duration,
                "fps": 8,
                "interpolation": True,
            },
            timeout=300.0,
        )
        response.raise_for_status()
        
        result = response.json()
        job_id = result["job_id"]
        
        # Poll for completion (video takes longer)
        video_path = _poll_job_completion(job_id, max_wait=600)
        
        if not video_path:
            raise self.retry(exc=Exception("Video generation timeout"))
        
        return {
            "status": "success",
            "video_path": video_path,
            "job_id": job_id,
            "duration": duration,
            "source_image": image_path,
        }
        
    except httpx.HTTPStatusError as e:
        logger.error(f"Video generation API error: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"Video generation failed: {e}")
        raise self.retry(exc=e)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def generate_cover_image(
    self,
    video_path: str,
    cover_text: str,
) -> dict[str, Any]:
    """Generate cover image for Reel.
    
    Args:
        video_path: Final video path
        cover_text: Text overlay for cover
        
    Returns:
        Cover image path
    """
    try:
        import subprocess
        from pathlib import Path
        
        output_path = video_path.replace(".mp4", "_cover.jpg")
        
        # Extract frame and add text
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", "00:00:01",
            "-vframes", "1",
            "-vf", (
                f"drawtext=text='{cover_text}':"
                "fontfile=/System/Library/Fonts/Supplemental/Arial Bold.ttf:"
                "fontsize=80:fontcolor=white:borderw=4:bordercolor=black:"
                "x=(w-text_w)/2:y=(h-text_h)/2"
            ),
            "-q:v", "2",
            output_path,
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        return {
            "status": "success",
            "cover_path": output_path,
            "text": cover_text,
        }
        
    except Exception as e:
        logger.error(f"Cover generation failed: {e}")
        raise self.retry(exc=e)


def _poll_job_completion(job_id: str, max_wait: int = 300) -> str | None:
    """Poll MLX server for job completion.
    
    Args:
        job_id: Generation job ID
        max_wait: Maximum wait time in seconds
        
    Returns:
        Output path if successful, None if timeout
    """
    import time
    
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            response = httpx.get(
                f"{MLX_SERVER_URL}/jobs/{job_id}",
                timeout=10.0,
            )
            response.raise_for_status()
            
            result = response.json()
            status = result.get("status")
            
            if status == "completed":
                return result.get("output_path")
            elif status == "failed":
                logger.error(f"Job {job_id} failed: {result.get('error_message')}")
                return None
            
            # Still pending or running
            time.sleep(5)
            
        except Exception as e:
            logger.warning(f"Poll error: {e}")
            time.sleep(5)
    
    logger.warning(f"Job {job_id} timeout after {max_wait}s")
    return None
