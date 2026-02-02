"""TrendScout API endpoints."""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel

from src.shared.database import get_session
from src.shared.logger import get_logger
from src.shared.models import TrendSource
from src.shared.orm_models import TrendORM
from src.trendscout.analyzer import TrendAnalyzer
from src.trendscout.scrapers import ScraperManager

logger = get_logger(__name__)
router = APIRouter()


class TrendScoutRequest(BaseModel):
    """Manual trend scouting request."""
    source: TrendSource | None = None
    limit: int = 25


class TrendScoutResponse(BaseModel):
    """Trend scouting response."""
    message: str
    trends_found: int
    trends: list[dict[str, Any]]


@router.post(
    "/scout",
    response_model=TrendScoutResponse,
    status_code=status.HTTP_200_OK,
    summary="Manually trigger trend scouting",
)
async def scout_trends(request: TrendScoutRequest) -> TrendScoutResponse:
    """Manually trigger trend scouting from specified sources."""
    scraper_manager = ScraperManager()
    analyzer = TrendAnalyzer()
    
    try:
        if request.source:
            raw_data = {
                request.source: await scraper_manager.scrape_source(
                    request.source, request.limit
                )
            }
        else:
            raw_data = await scraper_manager.scrape_all(request.limit)
        
        analyzed = await analyzer.analyze_trends(raw_data)
        
        # Store trends with score >= 50
        high_value = [t for t in analyzed if t["virality_score"] >= 50]
        
        async with get_session() as session:
            for trend_data in high_value:
                try:
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
        
        return TrendScoutResponse(
            message="Trend scouting completed",
            trends_found=len(analyzed),
            trends=analyzed[:10],  # Return top 10
        )
        
    except Exception as e:
        logger.error(f"Trend scouting failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Trend scouting failed: {str(e)}",
        )
    finally:
        await analyzer.close()


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    summary="Get stored trends",
)
async def get_trends(
    status: str | None = Query(None, description="Filter by status"),
    source: TrendSource | None = Query(None, description="Filter by source"),
    min_score: int = Query(0, ge=0, le=100, description="Minimum virality score"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """Get stored trends with optional filtering."""
    async with get_session() as session:
        from sqlalchemy import select
        from sqlalchemy import desc
        
        query = select(TrendORM).order_by(desc(TrendORM.score))
        
        if status:
            query = query.where(TrendORM.status == status)
        if source:
            query = query.where(TrendORM.source == source)
        if min_score > 0:
            query = query.where(TrendORM.score >= min_score)
        
        query = query.offset(offset).limit(limit)
        
        result = await session.execute(query)
        trends = result.scalars().all()
        
        return [
            {
                "id": t.id,
                "source": t.source.value,
                "title": t.title,
                "score": t.score,
                "status": t.status,
                "discovered_at": t.discovered_at.isoformat(),
                "url": t.url,
            }
            for t in trends
        ]


@router.get(
    "/{trend_id}",
    response_model=dict[str, Any],
    summary="Get trend details",
)
async def get_trend(trend_id: str) -> dict[str, Any]:
    """Get detailed information about a specific trend."""
    async with get_session() as session:
        trend = await session.get(TrendORM, trend_id)
        
        if not trend:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Trend not found",
            )
        
        return {
            "id": trend.id,
            "source": trend.source.value,
            "title": trend.title,
            "raw_data": trend.raw_data,
            "url": trend.url,
            "score": trend.score,
            "status": trend.status,
            "discovered_at": trend.discovered_at.isoformat(),
            "processed_at": trend.processed_at.isoformat() if trend.processed_at else None,
        }
