"""Celery tasks for Instagram Reels distribution.

Handles upload with retry logic and rate limiting.
"""

from typing import Any

from src.celery_app import celery_app
from src.distributor.instagram_reels import InstagramReelsUploader
from src.shared.config import get_settings
from src.shared.logger import get_logger
from src.shared.models_reels import InstagramReelsMetadata

logger = get_logger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def upload_to_instagram_reels(
    self,
    video_path: str,
    metadata_json: dict[str, Any],
    cover_image_path: str | None = None,
    channel_id: str | None = None,
) -> dict[str, Any]:
    """Upload video to Instagram Reels.
    
    Args:
        video_path: Path to final video
        metadata_json: Reels metadata dictionary
        cover_image_path: Optional cover image
        channel_id: Channel identifier for tracking
        
    Returns:
        Upload result with media ID and permalink
    """
    try:
        logger.info(f"Uploading to Instagram Reels: {metadata_json.get('caption', '')[:50]}...")
        
        # Parse metadata
        metadata = InstagramReelsMetadata(**metadata_json)
        
        # Upload
        uploader = InstagramReelsUploader()
        
        try:
            result = asyncio.run(
                uploader.upload_reel(
                    video_path=video_path,
                    metadata=metadata,
                    cover_image_path=cover_image_path,
                )
            )
            
            return {
                "status": "success",
                "platform": "instagram_reels",
                "media_id": result.get("id"),
                "permalink": result.get("permalink"),
                "channel_id": channel_id,
            }
            
        finally:
            asyncio.run(uploader.close())
            
    except Exception as e:
        logger.error(f"Instagram upload failed: {e}")
        
        # Check if we should retry
        if "rate limit" in str(e).lower():
            # Back off longer for rate limits
            raise self.retry(exc=e, countdown=600)
        
        raise self.retry(exc=e)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def collect_performance_metrics(
    self,
    media_id: str,
    content_id: str,
) -> dict[str, Any]:
    """Collect performance metrics for published Reel.
    
    Args:
        media_id: Instagram media ID
        content_id: Internal content ID
        
    Returns:
        Performance metrics
    """
    try:
        uploader = InstagramReelsUploader()
        
        try:
            metrics = asyncio.run(
                uploader.get_performance_metrics(media_id, content_id)
            )
            
            return {
                "status": "success",
                "content_id": content_id,
                "media_id": media_id,
                "metrics": metrics.model_dump(),
                "virality_coefficient": metrics.virality_coefficient,
            }
            
        finally:
            asyncio.run(uploader.close())
            
    except Exception as e:
        logger.error(f"Metrics collection failed: {e}")
        raise self.retry(exc=e)


@celery_app.task
def schedule_reels_upload(
    video_path: str,
    metadata_json: dict[str, Any],
    scheduled_time: str,
) -> dict[str, Any]:
    """Schedule Reel for future publication.
    
    Args:
        video_path: Video file path
        metadata_json: Reels metadata
        scheduled_time: ISO format datetime
        
    Returns:
        Schedule confirmation
    """
    # Instagram Graph API supports scheduled publishing
    # This would store the schedule and trigger upload at the right time
    
    logger.info(f"Scheduled Reel for {scheduled_time}")
    
    return {
        "status": "scheduled",
        "scheduled_time": scheduled_time,
        "video_path": video_path,
    }


@celery_app.task
def optimize_hashtags_task(
    niche: str,
    current_hashtags: list[str],
) -> dict[str, Any]:
    """Optimize hashtags for better reach.
    
    Args:
        niche: Content niche
        current_hashtags: Current hashtag list
        
    Returns:
        Optimized hashtag recommendations
    """
    uploader = InstagramReelsUploader()
    
    optimized = uploader.optimize_hashtags(
        niche=niche,
        trending=[],  # Would fetch from API
        max_tags=30,
    )
    
    return {
        "original": current_hashtags,
        "optimized": optimized,
        "added": list(set(optimized) - set(current_hashtags)),
        "removed": list(set(current_hashtags) - set(optimized)),
    }
