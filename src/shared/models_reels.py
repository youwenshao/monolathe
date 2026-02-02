"""Instagram Reels-specific Pydantic models."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.shared.models import ScriptSegment, VideoScript


class VideoFormat(str, Enum):
    """Video format specifications."""
    REELS_9_16 = "9:16"
    STANDARD_16_9 = "16:9"
    SQUARE_1_1 = "1:1"


class ReelsSpecs(BaseModel):
    """Instagram Reels technical specifications."""
    model_config = ConfigDict(frozen=True)
    
    aspect_ratio: str = "9:16"
    width: int = 1080
    height: int = 1920
    min_duration: float = 15.0
    max_duration: float = 90.0
    target_duration: float = Field(default=45.0, ge=15.0, le=90.0)
    fps: int = 30
    video_codec: str = "H.264"
    video_bitrate: str = "10M"
    audio_codec: str = "AAC"
    audio_bitrate: str = "128k"
    max_file_size_mb: int = 4000
    
    @property
    def resolution(self) -> str:
        """Get resolution string."""
        return f"{self.width}x{self.height}"
    
    @property
    def safe_zone_top(self) -> int:
        """Top safe zone for text (avoid profile overlay)."""
        return 250
    
    @property
    def safe_zone_bottom(self) -> int:
        """Bottom safe zone for text (avoid UI elements)."""
        return 300


class ContentStyle(str, Enum):
    """Content style presets."""
    FACELESS_REELS = "faceless_reels"
    DOCUSERIES_REELS = "docuseries_reels"
    TALKING_HEAD = "talking_head"
    SCREEN_RECORD = "screen_record"


class TextCard(BaseModel):
    """On-screen text card for Reels."""
    model_config = ConfigDict(frozen=True)
    
    text: str = Field(..., max_length=50)
    start_time: float = Field(ge=0)
    duration: float = Field(default=3.0, ge=1.0, le=10.0)
    position: str = Field(default="center", pattern="^(top|center|bottom)$")
    animation: str = Field(default="slide_up", pattern="^(slide_up|fade_in|typewriter|none)$")
    font_size: int = Field(default=72, ge=36, le=120)
    font_color: str = Field(default="#FFFFFF")
    outline_color: str = Field(default="#000000")
    outline_width: int = Field(default=3, ge=1, le=5)


class AudioStyle(BaseModel):
    """Audio configuration for Reels."""
    model_config = ConfigDict(frozen=True)
    
    voiceover_volume: float = Field(default=1.0, ge=0.0, le=1.0)
    music_volume: float = Field(default=0.3, ge=0.0, le=0.5)
    sound_effects: list[dict[str, Any]] = Field(default_factory=list)
    trending_audio_id: str | None = None
    use_original_audio: bool = Field(default=False)


class ReelsScriptSegment(ScriptSegment):
    """Extended script segment for Reels with visual timing."""
    model_config = ConfigDict(frozen=True)
    
    text_cards: list[TextCard] = Field(default_factory=list)
    b_roll_clips: list[str] = Field(default_factory=list)
    transition_type: str = Field(default="cut", pattern="^(cut|fade|slide|zoom)$")
    visual_hook: str | None = None  # Description of visual hook for this segment


class ReelsVideoScript(VideoScript):
    """Video script optimized for Instagram Reels."""
    model_config = ConfigDict(from_attributes=True)
    
    format_specs: ReelsSpecs = Field(default_factory=ReelsSpecs)
    content_style: ContentStyle = ContentStyle.FACELESS_REELS
    body: list[ReelsScriptSegment] = Field(default_factory=list)
    audio_style: AudioStyle = Field(default_factory=AudioStyle)
    cover_text: str = Field(default="", max_length=50)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    trending_audio_suggestion: str | None = None
    
    @field_validator("hashtags")
    @classmethod
    def validate_hashtags(cls, v: list[str]) -> list[str]:
        """Validate hashtag count and format."""
        if len(v) > 30:
            raise ValueError("Maximum 30 hashtags allowed")
        return [tag.lstrip("#") for tag in v]
    
    @property
    def total_duration(self) -> float:
        """Calculate total script duration."""
        return sum(seg.duration_seconds or 0 for seg in self.body)
    
    @property
    def is_duration_valid(self) -> bool:
        """Check if duration is within Reels limits."""
        duration = self.total_duration
        return 15 <= duration <= 90


class GenerationJob(BaseModel):
    """Asset generation job tracking."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(default_factory=uuid4)
    content_id: UUID
    job_type: str  # voice, image, video, assembly
    status: str = "pending"  # pending, running, completed, failed
    priority: int = Field(default=5, ge=1, le=10)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    output_path: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class GenerationMetrics(BaseModel):
    """Quantitative metrics for generation performance."""
    model_config = ConfigDict(frozen=True)
    
    job_id: UUID
    job_type: str
    duration_seconds: float
    vram_peak_gb: float
    cpu_percent: float
    output_quality_score: float | None = None
    transcribed_accuracy: float | None = None
    ssim_score: float | None = None
    
    @property
    def efficiency_score(self) -> float:
        """Calculate efficiency score based on time and resources."""
        # Lower is better for time, lower VRAM is better
        time_score = max(0, 1 - (self.duration_seconds / 300))  # 5 min baseline
        vram_score = max(0, 1 - (self.vram_peak_gb / 48))
        return (time_score + vram_score) / 2


class InstagramReelsMetadata(BaseModel):
    """Metadata for Instagram Reels upload."""
    model_config = ConfigDict(from_attributes=True)
    
    content_id: UUID
    caption: str = Field(..., max_length=2200)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    cover_image_path: str | None = None
    share_to_feed: bool = True
    allow_comments: bool = True
    allow_likes: bool = True
    audio_attribution: str | None = None
    collaboration_accounts: list[str] = Field(default_factory=list)
    location_id: str | None = None
    
    @property
    def caption_with_hashtags(self) -> str:
        """Generate full caption with hashtags."""
        hashtag_str = " ".join(f"#{tag}" for tag in self.hashtags[:30])
        return f"{self.caption}\n\n{hashtag_str}".strip()


class PerformanceMetrics(BaseModel):
    """Post-publication performance tracking."""
    model_config = ConfigDict(from_attributes=True)
    
    content_id: UUID
    platform: str = "instagram"
    media_id: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    reach: int = 0
    engagement_rate: float = 0.0
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    
    @property
    def virality_coefficient(self) -> float:
        """Calculate virality coefficient."""
        if self.views == 0:
            return 0.0
        return (self.likes + self.comments * 3 + self.shares * 5 + self.saves * 2) / self.views


# Re-export base models
from src.shared.models import (
    ChannelPersona,
    ContentStatus,
    NicheCategory,
    Platform,
    ScheduledContent,
    ScriptSegment,
    TrendData,
    TrendSource,
    UploadJob,
    VideoScript,
    ViralityScore,
)
