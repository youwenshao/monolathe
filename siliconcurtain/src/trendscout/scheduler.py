"""APScheduler configuration for periodic trend scouting."""

from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.shared.database import get_session
from src.shared.logger import get_logger
from src.shared.models import TrendData, TrendSource
from src.shared.orm_models import TrendORM
from src.shared.redis_client import get_redis_client
from src.trendscout.analyzer import TrendAnalyzer
from src.trendscout.scrapers import ScraperManager

logger = get_logger(__name__)


class TrendScoutScheduler:
    """Scheduler for automated trend scouting."""
    
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler()
        self.scraper_manager = ScraperManager()
        self.analyzer = TrendAnalyzer()
        self._is_running = False
    
    def start(self) -> None:
        """Start the scheduler."""
        if self._is_running:
            return
        
        # Schedule trend scouting every 15 minutes
        self.scheduler.add_job(
            self.scout_trends,
            trigger=CronTrigger(minute="*/15"),
            id="trend_scout",
            name="Trend Scouting Job",
            replace_existing=True,
        )
        
        self.scheduler.start()
        self._is_running = True
        logger.info("TrendScout scheduler started")
    
    def shutdown(self) -> None:
        """Shutdown the scheduler."""
        if self._is_running:
            self.scheduler.shutdown()
            self._is_running = False
            logger.info("TrendScout scheduler stopped")
    
    async def scout_trends(self) -> None:
        """Execute trend scouting job."""
        logger.info("Starting trend scouting job")
        
        try:
            # Check rate limit
            redis = await get_redis_client()
            allowed, remaining = await redis.rate_limit_check(
                key="trendscout:global",
                max_requests=60,
                window_seconds=60,
            )
            
            if not allowed:
                logger.warning("Rate limit exceeded, skipping trend scouting")
                return
            
            # Scrape all sources
            raw_trends = await self.scraper_manager.scrape_all(limit_per_source=20)
            
            # Analyze trends
            analyzed = await self.analyzer.analyze_trends(raw_trends)
            
            # Store high-value trends (score >= 60)
            high_value = [t for t in analyzed if t["virality_score"] >= 60]
            await self._store_trends(high_value)
            
            logger.info(f"Trend scouting complete. Stored {len(high_value)} high-value trends")
            
        except Exception as e:
            logger.error(f"Trend scouting job failed: {e}")
    
    async def _store_trends(self, analyzed_trends: list[dict]) -> None:
        """Store analyzed trends to database."""
        async with get_session() as session:
            for trend_data in analyzed_trends:
                try:
                    # Check for duplicate
                    existing = await session.get(TrendORM, trend_data["raw_data"].get("id"))
                    if existing:
                        continue
                    
                    trend = TrendORM(
                        source=TrendSource(trend_data["source"]),
                        title=trend_data["title"],
                        raw_data=trend_data["raw_data"],
                        url=trend_data["raw_data"].get("url"),
                        score=trend_data["virality_score"],
                        status="pending",
                    )
                    session.add(trend)
                    
                except Exception as e:
                    logger.error(f"Failed to store trend: {e}")
                    continue
    
    async def manual_scout(
        self,
        source: TrendSource | None = None,
        limit: int = 25,
    ) -> list[dict]:
        """Manually trigger trend scouting.
        
        Args:
            source: Specific source to scout, or None for all
            limit: Maximum trends per source
            
        Returns:
            List of analyzed trends
        """
        if source:
            raw_data = {source: await self.scraper_manager.scrape_source(source, limit)}
        else:
            raw_data = await self.scraper_manager.scrape_all(limit)
        
        analyzed = await self.analyzer.analyze_trends(raw_data)
        await self._store_trends(analyzed)
        
        return analyzed
