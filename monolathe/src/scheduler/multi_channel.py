"""Multi-channel scheduler for optimal posting times."""

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, and_

from src.shared.config import get_settings
from src.shared.database import get_session
from src.shared.logger import get_logger
from src.shared.models import NicheCategory
from src.shared.orm_models import ChannelORM, ScheduledContentORM

logger = get_logger(__name__)


class OptimalTimeCalculator:
    """Calculate optimal posting times for Reels."""
    
    BEST_TIMES = {
        "Monday": [9, 12, 19],
        "Tuesday": [9, 13, 20],
        "Wednesday": [11, 14, 21],
        "Thursday": [12, 15, 20],
        "Friday": [10, 13, 16, 22],
        "Saturday": [11, 14, 19],
        "Sunday": [10, 13, 20],
    }
    
    def calculate_optimal_times(
        self,
        category: NicheCategory,
        days_ahead: int = 7,
    ) -> list[datetime]:
        """Calculate optimal posting times."""
        slots = []
        now = datetime.utcnow()
        
        for day_offset in range(days_ahead):
            target_date = now + timedelta(days=day_offset)
            day_name = target_date.strftime("%A")
            base_times = self.BEST_TIMES.get(day_name, [12, 18])
            
            hour = random.choice(base_times)
            minute = random.randint(0, 59)
            
            slot = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            slots.append(slot)
        
        return slots


class MultiChannelScheduler:
    """Schedule content across multiple channels."""
    
    def __init__(self):
        self.settings = get_settings()
        self.time_calculator = OptimalTimeCalculator()
        self._scheduled_posts: dict[str, list[datetime]] = {}
    
    async def schedule_content(
        self,
        content_id: str,
        channel_id: str,
    ) -> datetime:
        """Schedule content for optimal time."""
        async with get_session() as session:
            result = await session.execute(
                select(ChannelORM).where(ChannelORM.id == channel_id)
            )
            channel = result.scalar_one_or_none()
            
            if not channel:
                raise ValueError(f"Channel {channel_id} not found")
            
            optimal_times = self.time_calculator.calculate_optimal_times(
                category=channel.niche_category,
                days_ahead=7,
            )
            
            # Find non-conflicting slot
            existing_posts = self._scheduled_posts.get(channel_id, [])
            
            for slot in optimal_times:
                min_gap = timedelta(hours=3)
                has_conflict = any(
                    abs((slot - existing).total_seconds()) < min_gap.total_seconds()
                    for existing in existing_posts
                )
                
                if not has_conflict:
                    self._scheduled_posts.setdefault(channel_id, []).append(slot)
                    
                    # Update database
                    content_result = await session.execute(
                        select(ScheduledContentORM).where(ScheduledContentORM.id == content_id)
                    )
                    content = content_result.scalar_one_or_none()
                    
                    if content:
                        content.scheduled_publish_at = slot
                        await session.commit()
                    
                    logger.info(f"Content {content_id} scheduled for {slot}")
                    return slot
            
            return optimal_times[-1] if optimal_times else datetime.utcnow() + timedelta(days=1)
    
    async def get_schedule(
        self,
        channel_id: str | None = None,
        days: int = 7,
    ) -> dict[str, Any]:
        """Get posting schedule."""
        async with get_session() as session:
            start = datetime.utcnow()
            end = start + timedelta(days=days)
            
            query = select(ScheduledContentORM).where(
                and_(
                    ScheduledContentORM.scheduled_publish_at >= start,
                    ScheduledContentORM.scheduled_publish_at <= end,
                )
            )
            
            if channel_id:
                query = query.where(ScheduledContentORM.channel_id == channel_id)
            
            result = await session.execute(query)
            posts = result.scalars().all()
            
            schedule = {}
            for post in posts:
                date_key = post.scheduled_publish_at.strftime("%Y-%m-%d")
                if date_key not in schedule:
                    schedule[date_key] = []
                
                schedule[date_key].append({
                    "content_id": post.id,
                    "time": post.scheduled_publish_at.strftime("%H:%M"),
                    "status": post.status.value if hasattr(post.status, 'value') else str(post.status),
                })
            
            return {
                "total_posts": len(posts),
                "by_date": schedule,
            }
