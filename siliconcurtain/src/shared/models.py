"""Pydantic models for data validation and serialization."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ContentStatus(str, Enum):
    """Content production status."""
    DRAFTED = "drafted"
    ASSETS_READY = "assets_ready"
    RENDERING = "rendering"
    UPLOADED = "uploaded"
    PUBLISHED = "published"
    FAILED = "failed"


class Platform(str, Enum):
    """Supported social media platforms."""
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"


class NicheCategory(str, Enum):
    """Content niche categories."""
    FINANCE = "finance"
    RELATIONSHIPS = "relationships"
    TECHNOLOGY = "technology"
    HISTORY = "history"
    MYSTERY = "mystery"
    ENTERTAINMENT = "entertainment"


class TrendSource(str, Enum):
    """Sources for trend data."""
    REDDIT = "reddit"
    YOUTUBE = "youtube"
    TWITTER = "twitter"
    GOOGLE_TRENDS = "google_trends"


class ViralityScore(BaseModel):
    """Virality score calculation result."""
    model_config = ConfigDict(frozen=True)
    
    score: int = Field(ge=0, le=100, description="Virality score 0-100")
    reasoning: str = Field(description="Explanation for the score")
    target_demographic: list[str] = Field(default_factory=list)
    recommended_format: str = Field(default="short_form")


class TrendData(BaseModel):
    """Raw trend data from sources."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(default_factory=uuid4)
    source: TrendSource
    title: str
    raw_data: dict[str, Any]
    url: str | None = None
    score: int | None = Field(default=None, ge=0, le=100)
    status: str = "pending"
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: datetime | None = None


class ScriptSegment(BaseModel):
    """Individual segment of a video script."""
    model_config = ConfigDict(frozen=True)
    
    type: str  # hook, intro, body, cta, outro
    content: str
    duration_seconds: float | None = None
    visual_notes: str | None = None
    b_roll_suggestions: list[str] = Field(default_factory=list)


class VideoScript(BaseModel):
    """Generated video script."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(default_factory=uuid4)
    title: str
    hook: str
    intro: str
    body: list[ScriptSegment]
    cta: str
    outro: str = ""
    tags: list[str] = Field(default_factory=list)
    category: NicheCategory | str = "entertainment"
    estimated_duration: float = 0.0
    target_audience: list[str] = Field(default_factory=list)
    seo_description: str = ""


class ChannelPersona(BaseModel):
    """Channel configuration and persona."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(default_factory=uuid4)
    name: str
    platform_account_id: str = Field(..., description="Encrypted platform ID")
    niche_category: NicheCategory
    target_demographic: dict[str, Any] = Field(default_factory=dict)
    voice_config: dict[str, Any] = Field(default_factory=dict)
    visual_config: dict[str, Any] = Field(default_factory=dict)
    posting_window: dict[str, Any] = Field(default_factory=dict)
    active: bool = True
    last_upload_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ScheduledContent(BaseModel):
    """Content scheduled for publication."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(default_factory=uuid4)
    channel_id: UUID
    source_trend_id: UUID | None = None
    script_json: VideoScript | dict[str, Any]
    status: ContentStatus = ContentStatus.DRAFTED
    scheduled_publish_at: datetime | None = None
    youtube_video_id: str | None = None
    metadata_hash: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UploadJob(BaseModel):
    """Upload queue job."""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(default_factory=uuid4)
    content_id: UUID
    platform: Platform
    priority: int = Field(default=5, ge=1, le=10)
    retry_count: int = 0
    error_log: str | None = None
    reserved_by_worker: str | None = None
    reserved_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class HealthStatus(BaseModel):
    """Service health check status."""
    model_config = ConfigDict(frozen=True)
    
    status: str  # healthy, degraded, unhealthy
    version: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    checks: dict[str, bool] = Field(default_factory=dict)
    latency_ms: dict[str, float] = Field(default_factory=dict)
