"""SQLAlchemy ORM models for database tables."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.database import Base
from src.shared.models import ContentStatus, NicheCategory, Platform, TrendSource


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


class ChannelORM(Base):
    """Channel persona database model."""
    
    __tablename__ = "channels"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    niche_category: Mapped[NicheCategory] = mapped_column(
        Enum(NicheCategory), nullable=False
    )
    target_demographic: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    voice_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    visual_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    posting_window: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(default=True)
    last_upload_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    scheduled_content: Mapped[list["ScheduledContentORM"]] = relationship(
        back_populates="channel", lazy="selectin"
    )


class TrendORM(Base):
    """Trend data database model."""
    
    __tablename__ = "trends"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source: Mapped[TrendSource] = mapped_column(Enum(TrendSource), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    scheduled_content: Mapped[list["ScheduledContentORM"]] = relationship(
        back_populates="source_trend", lazy="selectin"
    )
    
    __table_args__ = (
        # Index for querying pending trends by source
        {"sqlite_autoincrement": True},
    )


class ScheduledContentORM(Base):
    """Scheduled content database model."""
    
    __tablename__ = "scheduled_content"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    source_trend_id: Mapped[str | None] = mapped_column(
        ForeignKey("trends.id", ondelete="SET NULL"), nullable=True
    )
    script_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[ContentStatus] = mapped_column(
        Enum(ContentStatus), default=ContentStatus.DRAFTED
    )
    scheduled_publish_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    youtube_video_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    
    # Relationships
    channel: Mapped["ChannelORM"] = relationship(back_populates="scheduled_content")
    source_trend: Mapped["TrendORM"] = relationship(back_populates="scheduled_content")
    upload_jobs: Mapped[list["UploadJobORM"]] = relationship(
        back_populates="content", lazy="selectin"
    )
    
    __table_args__ = (
        # Composite index for channel + status queries
        {"sqlite_autoincrement": True},
    )


class UploadJobORM(Base):
    """Upload job queue database model."""
    
    __tablename__ = "upload_jobs"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    content_id: Mapped[str] = mapped_column(
        ForeignKey("scheduled_content.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[Platform] = mapped_column(Enum(Platform), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    reserved_by_worker: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    content: Mapped["ScheduledContentORM"] = relationship(back_populates="upload_jobs")
