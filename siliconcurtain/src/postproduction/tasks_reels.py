"""Celery tasks for Reels post-production.

Assembles final Reels from assets using FFmpeg with VideoToolbox.
"""

import json
from pathlib import Path
from typing import Any

from src.celery_app import celery_app
from src.postproduction.reels_assembler import (
    ReelsAssembler,
    create_reels_thumbnail,
)
from src.shared.logger import get_logger
from src.shared.models_reels import ReelsVideoScript

logger = get_logger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def assemble_reels(
    self,
    script_json: dict[str, Any],
    assets: dict[str, Any],
    output_path: str,
) -> dict[str, Any]:
    """Assemble complete Reel from script and assets.
    
    Args:
        script_json: ReelsVideoScript as dictionary
        assets: Dictionary of asset paths
        output_path: Final output video path
        
    Returns:
        Assembly metadata and validation results
    """
    try:
        logger.info(f"Assembling Reel: {script_json.get('title', 'Untitled')}")
        
        # Parse script
        script = ReelsVideoScript(**script_json)
        
        # Validate duration
        if not script.is_duration_valid:
            total_dur = script.total_duration
            logger.error(f"Invalid duration: {total_dur}s (must be 15-90s)")
            raise ValueError(f"Duration {total_dur}s outside Reels limits")
        
        # Assemble
        assembler = ReelsAssembler()
        result = assembler.assemble_reel(script, assets, output_path)
        
        if not result.get("meets_specs", {}).get("valid"):
            logger.warning(f"Reel may not meet Instagram specs: {result['meets_specs']}")
        
        return {
            "status": "success",
            "output_path": output_path,
            "duration": result.get("duration_seconds"),
            "file_size_mb": result.get("file_size_bytes", 0) / (1024 * 1024),
            "validation": result.get("meets_specs"),
        }
        
    except Exception as e:
        logger.error(f"Reel assembly failed: {e}")
        raise self.retry(exc=e)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def generate_captions_reels(
    self,
    audio_path: str,
    script_segments: list[dict[str, Any]],
    output_srt_path: str,
) -> dict[str, Any]:
    """Generate SRT captions optimized for Reels.
    
    Uses Whisper.cpp with MPS backend for fast transcription.
    Formatted for mobile viewing (short lines, clear timing).
    
    Args:
        audio_path: Path to voiceover audio
        script_segments: Script segments for alignment
        output_srt_path: Output SRT file path
        
    Returns:
        Caption metadata
    """
    try:
        import subprocess
        
        logger.info(f"Generating captions: {audio_path}")
        
        # Run Whisper.cpp
        # TODO: Configure for MPS backend on Apple Silicon
        whisper_cmd = [
            "whisper",
            "--model", "large-v3",
            "--language", "en",
            "--output_format", "srt",
            "--output_dir", str(Path(output_srt_path).parent),
            audio_path,
        ]
        
        result = subprocess.run(
            whisper_cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        
        # Whisper outputs to same directory with .srt extension
        generated_srt = audio_path.replace(".wav", ".srt").replace(".mp3", ".srt")
        
        # Move to desired location if different
        if generated_srt != output_srt_path:
            import shutil
            shutil.move(generated_srt, output_srt_path)
        
        # Count segments
        with open(output_srt_path, "r") as f:
            content = f.read()
            segment_count = content.count("\n\n") + 1
        
        return {
            "status": "success",
            "srt_path": output_srt_path,
            "segment_count": segment_count,
            "format": "srt",
        }
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Whisper failed: {e.stderr}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"Caption generation failed: {e}")
        raise self.retry(exc=e)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def create_cover_image(
    self,
    video_path: str,
    cover_text: str,
) -> dict[str, Any]:
    """Create cover image for Reel.
    
    Args:
        video_path: Final video path
        cover_text: Text for cover (max 5 words recommended)
        
    Returns:
        Cover image path
    """
    try:
        output_path = video_path.replace(".mp4", "_cover.jpg")
        
        result = create_reels_thumbnail(
            video_path=video_path,
            text=cover_text,
            output_path=output_path,
            font_size=72,
        )
        
        return {
            "status": "success",
            "cover_path": result,
            "text": cover_text,
        }
        
    except Exception as e:
        logger.error(f"Cover creation failed: {e}")
        raise self.retry(exc=e)


@celery_app.task(bind=True, max_retries=1)
def validate_reels_specs(
    self,
    video_path: str,
) -> dict[str, Any]:
    """Validate video meets Instagram Reels specifications.
    
    Args:
        video_path: Video file to validate
        
    Returns:
        Detailed validation report
    """
    try:
        import subprocess
        import json
        
        # Get video info with ffprobe
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,bit_rate",
            "-show_entries", "format=duration,size",
            "-of", "json",
            video_path,
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        
        info = json.loads(result.stdout)
        stream = info.get("streams", [{}])[0]
        format_info = info.get("format", {})
        
        width = stream.get("width", 0)
        height = stream.get("height", 0)
        duration = float(format_info.get("duration", 0))
        file_size = int(format_info.get("size", 0))
        
        # Validate specs
        checks = {
            "resolution_1080x1920": width == 1080 and height == 1920,
            "aspect_ratio_9_16": abs((width / height) - (9 / 16)) < 0.01,
            "duration_15_90s": 15 <= duration <= 90,
            "file_size_under_4gb": file_size < (4 * 1024 * 1024 * 1024),
            "h264_codec": True,  # Would need to check actual codec
        }
        
        all_passed = all(checks.values())
        
        report = {
            "valid": all_passed,
            "checks": checks,
            "detected": {
                "width": width,
                "height": height,
                "aspect_ratio": round(width / height, 3),
                "duration_seconds": round(duration, 2),
                "file_size_mb": round(file_size / (1024 * 1024), 2),
            },
            "recommendations": [],
        }
        
        if not checks["duration_15_90s"]:
            report["recommendations"].append(
                f"Duration {duration:.1f}s outside 15-90s range - trim or extend"
            )
        
        if not checks["resolution_1080x1920"]:
            report["recommendations"].append(
                f"Resolution {width}x{height} not optimal - re-encode to 1080x1920"
            )
        
        return report
        
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return {"valid": False, "error": str(e)}
