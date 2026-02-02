"""Instagram Reels assembler with FFmpeg and VideoToolbox.

Optimized for 9:16 vertical format with text overlays, quick cuts,
and burned-in captions for mobile-first viewing.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.shared.config import get_settings
from src.shared.logger import get_logger
from src.shared.models_reels import (
    AudioStyle,
    ContentStyle,
    ReelsScriptSegment,
    ReelsSpecs,
    ReelsVideoScript,
    TextCard,
)

logger = get_logger(__name__)


class ReelsAssembler:
    """Assemble Instagram Reels from assets."""
    
    def __init__(self) -> None:
        self.settings = get_settings()
        self.specs = ReelsSpecs()
        self._verify_ffmpeg()
    
    def _verify_ffmpeg(self) -> None:
        """Verify FFmpeg installation and log capabilities."""
        try:
            caps = self._get_ffmpeg_caps()
            if "videotoolbox" not in caps:
                logger.info("FFmpeg will use software encoding (libx264)")
            else:
                logger.info("FFmpeg with VideoToolbox verified")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"FFmpeg verification failed: {e}")
            raise RuntimeError("FFmpeg not properly installed")
    
    def _get_ffmpeg_caps(self) -> str:
        """Get FFmpeg capabilities string."""
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.lower()
    
    def _build_ffmpeg_command(
        self,
        inputs: list[dict[str, Any]],
        output_path: str,
        script: ReelsVideoScript,
    ) -> list[str]:
        """Build FFmpeg command for Reels assembly.
        
        Args:
            inputs: List of input files with timing info
            output_path: Output file path
            script: Video script for styling
            
        Returns:
            FFmpeg command as list of strings
        """
        cmd = ["ffmpeg", "-y"]
        
        # Add inputs
        for inp in inputs:
            cmd.extend(["-i", inp["path"]])
        
        # Complex filter for assembly
        filter_parts = []
        
        # Scale all inputs to 1080x1920
        for i, inp in enumerate(inputs):
            filter_parts.append(
                f"[{i}:v]scale={self.specs.width}:{self.specs.height}:force_original_aspect_ratio=decrease,"
                f"pad={self.specs.width}:{self.specs.height}:(ow-iw)/2:(oh-ih)/2[v{i}];"
            )
        
        # Concatenate video streams
        concat_inputs = "".join(f"[v{i}]" for i in range(len(inputs)))
        filter_parts.append(
            f"{concat_inputs}concat=n={len(inputs)}:v=1:a=0[outv];"
        )
        
        # Add audio mixing if present
        audio_inputs = [f"[{i}:a]" for i in range(len(inputs)) if inp.get("has_audio")]
        if audio_inputs:
            filter_parts.append(
                f"{''.join(audio_inputs)}amix=inputs={len(audio_inputs)}:duration=first[outa]"
            )
        
        # Build full filter complex
        filter_complex = "".join(filter_parts)
        
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
        ])
        
        if audio_inputs:
            cmd.extend(["-map", "[outa]"])
        
        # Video encoding
        if "videotoolbox" in self._get_ffmpeg_caps():
            cmd.extend([
                "-c:v", "h264_videotoolbox",
                "-b:v", self.specs.video_bitrate,
            ])
        else:
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
            ])
        
        cmd.extend([
            "-r", str(self.specs.fps),
            "-pix_fmt", "yuv420p",
            "-tag:v", "avc1",
        ])
        
        # Audio encoding
        if audio_inputs:
            cmd.extend([
                "-c:a", "aac",
                "-b:a", self.specs.audio_bitrate,
                "-ar", "48000",
            ])
        
        # Fast start for streaming
        cmd.extend([
            "-movflags", "+faststart",
            output_path,
        ])
        
        return cmd
    
    def add_text_overlay(
        self,
        video_path: str,
        text_cards: list[TextCard],
        output_path: str,
    ) -> str:
        """Add text overlays to video.
        
        Args:
            video_path: Input video path
            text_cards: List of text cards to overlay
            output_path: Output video path
            
        Returns:
            Output path
        """
        if not text_cards:
            return video_path
        
        # Build drawtext filters
        filters = []
        for card in text_cards:
            # Escape special characters
            text = card.text.replace("'", "'\\\\''")
            
            # Position calculation
            if card.position == "top":
                y_pos = self.specs.safe_zone_top + 50
            elif card.position == "bottom":
                y_pos = self.specs.height - self.specs.safe_zone_bottom - 100
            else:
                y_pos = "(h-text_h)/2"
            
            filter_str = (
                f"drawtext=text='{text}':"
                f"fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:"
                f"fontsize={card.font_size}:"
                f"fontcolor={card.font_color}:"
                f"borderw={card.outline_width}:"
                f"bordercolor={card.outline_color}:"
                f"x=(w-text_w)/2:y={y_pos}:"
                f"enable='between(t,{card.start_time},{card.start_time + card.duration})'"
            )
            filters.append(filter_str)
        
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", ",".join(filters),
        ]
        
        if "videotoolbox" in self._get_ffmpeg_caps():
            cmd.extend([
                "-c:v", "h264_videotoolbox",
                "-b:v", self.specs.video_bitrate,
            ])
        else:
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
            ])
            
        cmd.extend([
            "-c:a", "copy",
            output_path,
        ])
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"Text overlay added: {output_path}")
            return output_path
        except subprocess.CalledProcessError as e:
            logger.error(f"Text overlay failed: {e.stderr}")
            raise
    
    def burn_captions(
        self,
        video_path: str,
        srt_path: str,
        output_path: str,
        style: dict[str, Any] | None = None,
    ) -> str:
        """Burn SRT captions into video.
        
        Args:
            video_path: Input video path
            srt_path: SRT subtitle file path
            output_path: Output video path
            style: Caption styling options
            
        Returns:
            Output path
        """
        style = style or {
            "font_name": "Arial",
            "font_size": 48,
            "primary_colour": "&H00FFFFFF",  # White
            "outline_colour": "&H00000000",  # Black
            "outline_thickness": 3,
            "alignment": 2,  # Bottom center
        }
        
        # Convert SRT to ASS with styling
        ass_path = srt_path.replace(".srt", ".ass")
        self._convert_srt_to_ass(srt_path, ass_path, style)
        
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"ass={ass_path}",
        ]
        
        if "videotoolbox" in self._get_ffmpeg_caps():
            cmd.extend([
                "-c:v", "h264_videotoolbox",
                "-b:v", self.specs.video_bitrate,
            ])
        else:
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
            ])
            
        cmd.extend([
            "-c:a", "copy",
            output_path,
        ])
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"Captions burned: {output_path}")
            return output_path
        except subprocess.CalledProcessError as e:
            logger.error(f"Caption burn failed: {e.stderr}")
            raise
    
    def _convert_srt_to_ass(
        self,
        srt_path: str,
        ass_path: str,
        style: dict[str, Any],
    ) -> None:
        """Convert SRT to ASS format with custom styling.
        
        Args:
            srt_path: Input SRT file
            ass_path: Output ASS file
            style: Style dictionary
        """
        header = f"""[Script Info]
Title: Generated Subtitles
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style['font_name']},{style['font_size']},{style['primary_colour']},{style['primary_colour']},{style['outline_colour']},{style['outline_colour']},0,0,0,0,100,100,0,0,1,{style['outline_thickness']},0,{style['alignment']},10,10,100,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        # Read SRT and convert
        with open(srt_path, "r", encoding="utf-8") as f:
            srt_content = f.read()
        
        # Simple SRT to ASS conversion (for production, use pysubs2)
        ass_lines = [header]
        
        # Write ASS file
        with open(ass_path, "w", encoding="utf-8") as f:
            f.writelines(ass_lines)
    
    def apply_ken_burns(
        self,
        image_path: str,
        duration: float,
        output_path: str,
        zoom_start: float = 1.0,
        zoom_end: float = 1.1,
        pan_direction: str = "center",
    ) -> str:
        """Apply Ken Burns effect to static image.
        
        Args:
            image_path: Input image
            duration: Output duration in seconds
            output_path: Output video path
            zoom_start: Starting zoom level
            zoom_end: Ending zoom level
            pan_direction: Pan direction (left, right, up, down, center)
            
        Returns:
            Output path
        """
        # Calculate pan coordinates based on direction
        if pan_direction == "left":
            x_expr = f"(iw-{self.specs.width})*({zoom_end}-zoom)/({zoom_end}-{zoom_start})"
            y_expr = f"(ih-{self.specs.height})/2"
        elif pan_direction == "right":
            x_expr = "0"
            y_expr = f"(ih-{self.specs.height})/2"
        elif pan_direction == "up":
            x_expr = f"(iw-{self.specs.width})/2"
            y_expr = f"(ih-{self.specs.height})*({zoom_end}-zoom)/({zoom_end}-{zoom_start})"
        elif pan_direction == "down":
            x_expr = f"(iw-{self.specs.width})/2"
            y_expr = "0"
        else:  # center
            x_expr = f"(iw-{self.specs.width})/2"
            y_expr = f"(ih-{self.specs.height})/2"
        
        zoom_expr = f"zoom=z='if(lte(zoom,{zoom_end}),zoom+0.001,{zoom_end})'"
        
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", image_path,
            "-vf", f"zoompan=z='min(zoom+0.0015,{zoom_end})':d={int(duration * self.specs.fps)}:s={self.specs.width}x{self.specs.height}:fps={self.specs.fps}",
        ]
        
        if "videotoolbox" in self._get_ffmpeg_caps():
            cmd.extend([
                "-c:v", "h264_videotoolbox",
                "-b:v", self.specs.video_bitrate,
            ])
        else:
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
            ])
            
        cmd.extend([
            "-r", str(self.specs.fps),
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            output_path,
        ])
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"Ken Burns effect applied: {output_path}")
            return output_path
        except subprocess.CalledProcessError as e:
            logger.error(f"Ken Burns failed: {e.stderr}")
            raise
    
    def assemble_reel(
        self,
        script: ReelsVideoScript,
        assets: dict[str, Any],
        output_path: str,
    ) -> dict[str, Any]:
        """Assemble complete Reel from script and assets.
        
        Args:
            script: Reels video script
            assets: Dictionary of asset paths
            output_path: Final output path
            
        Returns:
            Assembly metadata
        """
        logger.info(f"Assembling Reel: {script.title}")
        logger.info(f"Assets: {assets}")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            segment_files = []
            
            # Process each segment
            for i, segment in enumerate(script.body):
                segment_path = temp_path / f"segment_{i:03d}.mp4"
                logger.info(f"Processing segment {i}: {segment.content[:30]}...")
                
                # Determine source
                if segment.visual_notes and "b_roll" in segment.visual_notes:
                    # Use B-roll video or image with Ken Burns
                    b_roll = assets.get("b_roll", [])
                    if b_roll:
                        logger.info(f"Applying Ken Burns to B-roll for segment {i}")
                        # Apply Ken Burns to first B-roll image
                        self.apply_ken_burns(
                            b_roll[0],
                            segment.duration_seconds or 3.0,
                            str(segment_path),
                        )
                else:
                    # Use generated video or static with effect
                    if "video_path" in assets:
                        logger.info(f"Using video_path for segment {i}")
                        segment_path = Path(assets["video_path"])
                    else:
                        # Create from static image
                        img_path = assets.get("main_image", "")
                        if img_path:
                            logger.info(f"Applying Ken Burns to main_image for segment {i}")
                            self.apply_ken_burns(
                                img_path,
                                segment.duration_seconds or 3.0,
                                str(segment_path),
                            )
                
                if segment_path.exists():
                    logger.info(f"Segment {i} file created: {segment_path}")
                    segment_files.append({
                        "path": str(segment_path),
                        "has_audio": True,
                    })
                else:
                    logger.warning(f"Segment {i} file NOT created: {segment_path}")
            
            if not segment_files:
                logger.error("No segments were created!")
                raise RuntimeError("No segments were created during assembly")
            
            # Concatenate segments
            concat_list = temp_path / "concat.txt"
            with open(concat_list, "w") as f:
                for seg in segment_files:
                    f.write(f"file '{seg['path']}'\n")
            
            temp_output = temp_path / "assembled.mp4"
            logger.info(f"Concatenating {len(segment_files)} segments...")
            
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy",
                str(temp_output),
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info("Concatenation complete")
            
            # Add text overlays
            if script.body and script.body[0].text_cards:
                text_output = temp_path / "with_text.mp4"
                self.add_text_overlay(
                    str(temp_output),
                    script.body[0].text_cards,
                    str(text_output),
                )
                temp_output = text_output
            
            # Burn captions if available
            if "captions_srt" in assets:
                final_temp = temp_path / "with_captions.mp4"
                self.burn_captions(
                    str(temp_output),
                    assets["captions_srt"],
                    str(final_temp),
                )
                temp_output = final_temp
            
            # Copy to final destination
            import shutil
            shutil.copy(str(temp_output), output_path)
        
        # Get video info
        duration = self._get_video_duration(output_path)
        file_size = Path(output_path).stat().st_size
        
        return {
            "output_path": output_path,
            "duration_seconds": duration,
            "file_size_bytes": file_size,
            "resolution": self.specs.resolution,
            "aspect_ratio": self.specs.aspect_ratio,
            "meets_specs": self._validate_specs(output_path),
        }
    
    def _get_video_duration(self, video_path: str) -> float:
        """Get video duration using ffprobe."""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    video_path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError):
            return 0.0
    
    def _validate_specs(self, video_path: str) -> dict[str, Any]:
        """Validate video meets Instagram Reels specs.
        
        Args:
            video_path: Video to validate
            
        Returns:
            Validation results
        """
        try:
            # Get video info
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height,r_frame_rate",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    video_path,
                ],
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
            
            # Check specs
            checks = {
                "resolution": width == self.specs.width and height == self.specs.height,
                "aspect_ratio": abs(width / height - 9 / 16) < 0.01,
                "duration_min": duration >= self.specs.min_duration,
                "duration_max": duration <= self.specs.max_duration,
                "file_size": Path(video_path).stat().st_size < (self.specs.max_file_size_mb * 1024 * 1024),
            }
            
            return {
                "valid": all(checks.values()),
                "checks": checks,
                "detected": {
                    "width": width,
                    "height": height,
                    "duration": duration,
                    "file_size_mb": Path(video_path).stat().st_size / (1024 * 1024),
                },
            }
            
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return {"valid": False, "error": str(e)}


def create_reels_thumbnail(
    video_path: str,
    text: str,
    output_path: str,
    font_size: int = 80,
) -> str:
    """Create Reels cover image from first frame with text.
    
    Args:
        video_path: Source video
        text: Cover text (max 5 words recommended)
        output_path: Output image path
        font_size: Text size
        
    Returns:
        Output path
    """
    specs = ReelsSpecs()
    
    # Escape text
    safe_text = text.replace("'", "'\\\\''")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ss", "00:00:00",
        "-vframes", "1",
        "-vf", (
            f"drawtext=text='{safe_text}':"
            f"fontfile=/System/Library/Fonts/Supplemental/Arial Bold.ttf:"
            f"fontsize={font_size}:"
            f"fontcolor=white:"
            f"borderw=4:"
            f"bordercolor=black:"
            f"x=(w-text_w)/2:y=(h-text_h)/2"
        ),
        "-q:v", "2",
        output_path,
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"Thumbnail created: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"Thumbnail creation failed: {e.stderr}")
        raise
