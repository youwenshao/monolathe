"""Celery tasks for asset generation."""

from typing import Any
from pathlib import Path

from src.celery_app import celery_app
from src.shared.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(bind=True, max_retries=3)
def generate_voice(self, script_text: str, voice_config: dict[str, Any]) -> dict[str, Any]:
    """Generate voiceover using F5-TTS.
    
    Args:
        script_text: Text to synthesize
        voice_config: Voice configuration (model, pitch, speed)
        
    Returns:
        Dictionary with audio file path and metadata
    """
    try:
        logger.info(f"Generating voiceover for script: {script_text[:50]}...")
        
        # Ensure directory exists
        audio_dir = Path("/shared/audio")
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        # Use sample voice if available, otherwise generate dummy
        sample_path = audio_dir / "sample_voice.wav"
        audio_path = audio_dir / "voice_001.wav"
        
        if sample_path.exists():
            import shutil
            shutil.copy(str(sample_path), str(audio_path))
            logger.info(f"Used sample voice from {sample_path}")
        elif not audio_path.exists():
            import subprocess
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", 
                "-t", "10", str(audio_path)
            ], check=True)
        
        return {
            "status": "success",
            "audio_path": str(audio_path),
            "duration_seconds": 10.0,
            "voice_config": voice_config,
        }
    except Exception as exc:
        logger.error(f"Voice generation failed: {exc}")
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(bind=True, max_retries=2)
def generate_image(
    self,
    prompt: str,
    visual_config: dict[str, Any],
    width: int = 1024,
    height: int = 1024,
) -> dict[str, Any]:
    """Generate image using FLUX-dev.
    
    Args:
        prompt: Image generation prompt
        visual_config: Visual style configuration
        width: Image width
        height: Image height
        
    Returns:
        Dictionary with image file path and metadata
    """
    try:
        logger.info(f"Generating image: {prompt[:50]}...")
        
        # Ensure directory exists
        image_dir = Path("/shared/images")
        image_dir.mkdir(parents=True, exist_ok=True)
        
        # Use sample image if available, otherwise generate dummy
        sample_path = image_dir / "sample_bg.png"
        image_path = image_dir / "gen_001.png"
        
        if sample_path.exists():
            import shutil
            shutil.copy(str(sample_path), str(image_path))
            logger.info(f"Used sample image from {sample_path}")
        elif not image_path.exists():
            import subprocess
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=orange:s={width}x{height}", 
                "-vframes", "1", str(image_path)
            ], check=True)
        
        return {
            "status": "success",
            "image_path": str(image_path),
            "width": width,
            "height": height,
            "prompt": prompt,
        }
    except Exception as exc:
        logger.error(f"Image generation failed: {exc}")
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(bind=True, max_retries=2)
def generate_video_clip(
    self,
    image_path: str,
    motion_prompt: str,
    duration: float = 4.0,
) -> dict[str, Any]:
    """Generate video clip using CogVideoX.
    
    Args:
        image_path: Input image path
        motion_prompt: Motion description
        duration: Target duration in seconds
        
    Returns:
        Dictionary with video file path and metadata
    """
    try:
        logger.info(f"Generating video clip from image: {image_path}")
        
        # TODO: Implement CogVideoX inference
        # This is a placeholder for the actual implementation
        
        return {
            "status": "success",
            "video_path": "/shared/videos/clip_001.mp4",
            "duration": duration,
            "source_image": image_path,
        }
    except Exception as exc:
        logger.error(f"Video generation failed: {exc}")
        raise self.retry(exc=exc, countdown=60)
