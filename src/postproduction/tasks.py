"""Celery tasks for video post-production."""

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.celery_app import celery_app
from src.shared.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(bind=True, max_retries=2)
def assemble_video(
    self,
    script: dict[str, Any],
    assets: dict[str, Any],
    template: str = "faceless_v1",
) -> dict[str, Any]:
    """Assemble final video from assets.
    
    Args:
        script: Video script data
        assets: Dictionary of asset paths
        template: Assembly template name
        
    Returns:
        Dictionary with output video path and metadata
    """
    try:
        logger.info(f"Assembling video: {script.get('title', 'Untitled')}")
        
        from src.postproduction.reels_assembler import ReelsAssembler
        from src.shared.models_reels import ReelsVideoScript, ReelsScriptSegment
        from src.shared.models import VideoScript
        
        # Ensure output directory exists
        output_dir = Path("/shared/output")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = "/shared/output/final_video.mp4"
        
        # Convert dict or VideoScript to ReelsVideoScript if needed
        if isinstance(script, dict):
            body = []
            for s in script.get("body", []):
                if isinstance(s, dict):
                    body.append(ReelsScriptSegment(**s))
                else:
                    body.append(s)
            
            reels_script = ReelsVideoScript(
                title=script.get("title", "Untitled"),
                hook=script.get("hook", ""),
                intro=script.get("intro", ""),
                body=body,
                cta=script.get("cta", ""),
            )
        elif isinstance(script, VideoScript):
            reels_script = ReelsVideoScript(
                title=script.title,
                hook=script.hook,
                intro=script.intro,
                body=[ReelsScriptSegment(content=s.content, duration_seconds=s.duration_seconds or 3.0, visual_notes=s.visual_notes) for s in script.body],
                cta=script.cta,
            )
        else:
            reels_script = script

        assembler = ReelsAssembler()
        result = assembler.assemble_reel(reels_script, assets, output_path)
        
        return {
            "status": "success",
            "video_path": output_path,
            "duration": result.get("duration_seconds", 0),
            "resolution": result.get("resolution", "1080x1920"),
            "file_size": result.get("file_size_bytes", 0),
        }
    except Exception as exc:
        logger.error(f"Video assembly failed: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=120)


@celery_app.task(bind=True, max_retries=2)
def generate_thumbnail(
    self,
    video_path: str,
    title: str,
    visual_config: dict[str, Any],
) -> dict[str, Any]:
    """Generate video thumbnail.
    
    Args:
        video_path: Path to final video
        title: Video title for overlay
        visual_config: Visual style configuration
        
    Returns:
        Dictionary with thumbnail path
    """
    try:
        logger.info(f"Generating thumbnail for: {title}")
        
        # TODO: Implement thumbnail generation
        # - Extract keyframe from video
        # - Apply channel branding
        # - Add text overlay
        # - Apply color palette
        
        return {
            "status": "success",
            "thumbnail_path": "/shared/output/thumbnail.jpg",
            "title": title,
        }
    except Exception as exc:
        logger.error(f"Thumbnail generation failed: {exc}")
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(bind=True, max_retries=1)
def generate_subtitles(
    self,
    audio_path: str,
    script_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate SRT subtitles from audio.
    
    Args:
        audio_path: Path to voiceover audio
        script_segments: Script segments with timing
        
    Returns:
        Dictionary with SRT file path
    """
    try:
        logger.info(f"Generating subtitles for: {audio_path}")
        
        # TODO: Implement Whisper.cpp for transcription
        # - Run Whisper with MPS backend
        # - Align with script segments
        # - Generate SRT file
        
        return {
            "status": "success",
            "srt_path": "/shared/output/subtitles.srt",
            "segment_count": len(script_segments),
        }
    except Exception as exc:
        logger.error(f"Subtitle generation failed: {exc}")
        raise self.retry(exc=exc, countdown=30)
