"""Integration tests for database operations."""

import pytest
from sqlalchemy import select

from src.shared.models import ContentStatus, NicheCategory, Platform, TrendSource
from src.shared.orm_models import ChannelORM, ScheduledContentORM, TrendORM, UploadJobORM


class TestChannelORM:
    """Test cases for Channel ORM operations."""
    
    @pytest.mark.asyncio
    async def test_create_channel(self, db_session):
        """Test creating a channel."""
        channel = ChannelORM(
            name="Test Channel",
            platform_account_id="test_account",
            niche_category=NicheCategory.TECHNOLOGY,
            target_demographic={"age": "18-34"},
            voice_config={"model": "f5-tts"},
            visual_config={"colors": ["#000"]},
            posting_window={"start": 8, "end": 20},
            active=True,
        )
        
        db_session.add(channel)
        await db_session.commit()
        await db_session.refresh(channel)
        
        assert channel.id is not None
        assert channel.name == "Test Channel"
        assert channel.active is True
    
    @pytest.mark.asyncio
    async def test_channel_to_dict(self, db_session):
        """Test channel serialization."""
        channel = ChannelORM(
            name="Test",
            platform_account_id="test",
            niche_category=NicheCategory.FINANCE,
        )
        db_session.add(channel)
        await db_session.commit()
        
        data = channel.to_dict()
        assert data["name"] == "Test"
        assert data["niche_category"] == NicheCategory.FINANCE
    
    @pytest.mark.asyncio
    async def test_list_channels(self, db_session):
        """Test listing channels."""
        # Create multiple channels
        for i in range(3):
            channel = ChannelORM(
                name=f"Channel {i}",
                platform_account_id=f"account_{i}",
                niche_category=NicheCategory.ENTERTAINMENT,
            )
            db_session.add(channel)
        
        await db_session.commit()
        
        # Query channels
        result = await db_session.execute(select(ChannelORM))
        channels = result.scalars().all()
        
        assert len(channels) == 3


class TestTrendORM:
    """Test cases for Trend ORM operations."""
    
    @pytest.mark.asyncio
    async def test_create_trend(self, db_session):
        """Test creating a trend."""
        trend = TrendORM(
            source=TrendSource.REDDIT,
            title="Test Trend",
            raw_data={"score": 1000, "comments": 50},
            url="https://reddit.com/r/test",
            score=75,
            status="pending",
        )
        
        db_session.add(trend)
        await db_session.commit()
        await db_session.refresh(trend)
        
        assert trend.id is not None
        assert trend.title == "Test Trend"
        assert trend.score == 75
    
    @pytest.mark.asyncio
    async def test_filter_trends_by_source(self, db_session):
        """Test filtering trends by source."""
        # Create trends from different sources
        reddit_trend = TrendORM(
            source=TrendSource.REDDIT,
            title="Reddit Trend",
            raw_data={},
        )
        youtube_trend = TrendORM(
            source=TrendSource.YOUTUBE,
            title="YouTube Trend",
            raw_data={},
        )
        
        db_session.add_all([reddit_trend, youtube_trend])
        await db_session.commit()
        
        # Filter by Reddit
        result = await db_session.execute(
            select(TrendORM).where(TrendORM.source == TrendSource.REDDIT)
        )
        trends = result.scalars().all()
        
        assert len(trends) == 1
        assert trends[0].title == "Reddit Trend"


class TestScheduledContentORM:
    """Test cases for ScheduledContent ORM operations."""
    
    @pytest.mark.asyncio
    async def test_create_scheduled_content(self, db_session):
        """Test creating scheduled content."""
        # First create a channel
        channel = ChannelORM(
            name="Content Channel",
            platform_account_id="account",
            niche_category=NicheCategory.HISTORY,
        )
        db_session.add(channel)
        await db_session.commit()
        
        # Create scheduled content
        content = ScheduledContentORM(
            channel_id=channel.id,
            script_json={"title": "Test Script", "hook": "Hook text"},
            status=ContentStatus.DRAFTED,
            metadata_hash="abc123",
        )
        
        db_session.add(content)
        await db_session.commit()
        await db_session.refresh(content)
        
        assert content.id is not None
        assert content.status == ContentStatus.DRAFTED
        assert content.channel_id == channel.id
    
    @pytest.mark.asyncio
    async def test_content_status_transitions(self, db_session):
        """Test content status updates."""
        channel = ChannelORM(
            name="Test",
            platform_account_id="test",
            niche_category=NicheCategory.MYSTERY,
        )
        db_session.add(channel)
        await db_session.commit()
        
        content = ScheduledContentORM(
            channel_id=channel.id,
            script_json={},
            status=ContentStatus.DRAFTED,
        )
        db_session.add(content)
        await db_session.commit()
        
        # Update status
        content.status = ContentStatus.RENDERING
        await db_session.commit()
        await db_session.refresh(content)
        
        assert content.status == ContentStatus.RENDERING


class TestUploadJobORM:
    """Test cases for UploadJob ORM operations."""
    
    @pytest.mark.asyncio
    async def test_create_upload_job(self, db_session):
        """Test creating upload job."""
        # Setup dependencies
        channel = ChannelORM(
            name="Upload Channel",
            platform_account_id="account",
            niche_category=NicheCategory.RELATIONSHIPS,
        )
        db_session.add(channel)
        await db_session.commit()
        
        content = ScheduledContentORM(
            channel_id=channel.id,
            script_json={},
        )
        db_session.add(content)
        await db_session.commit()
        
        # Create upload job
        job = UploadJobORM(
            content_id=content.id,
            platform=Platform.YOUTUBE,
            priority=5,
        )
        
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)
        
        assert job.id is not None
        assert job.platform == Platform.YOUTUBE
        assert job.retry_count == 0
    
    @pytest.mark.asyncio
    async def test_job_reservation(self, db_session):
        """Test job reservation for workers."""
        channel = ChannelORM(
            name="Test",
            platform_account_id="test",
            niche_category=NicheCategory.ENTERTAINMENT,
        )
        db_session.add(channel)
        await db_session.commit()
        
        content = ScheduledContentORM(
            channel_id=channel.id,
            script_json={},
        )
        db_session.add(content)
        await db_session.commit()
        
        job = UploadJobORM(
            content_id=content.id,
            platform=Platform.INSTAGRAM,
        )
        db_session.add(job)
        await db_session.commit()
        
        # Reserve job
        job.reserved_by_worker = "worker-1"
        from datetime import datetime
        job.reserved_at = datetime.utcnow()
        await db_session.commit()
        await db_session.refresh(job)
        
        assert job.reserved_by_worker == "worker-1"
        assert job.reserved_at is not None
