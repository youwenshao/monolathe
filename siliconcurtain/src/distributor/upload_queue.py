"""Priority upload queue with Redis backend."""

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.shared.config import get_settings
from src.shared.logger import get_logger
from src.shared.redis_client import get_redis_client

logger = get_logger(__name__)

QUEUE_KEY = "upload:queue"
PROCESSING_KEY = "upload:processing"
FAILED_KEY = "upload:failed"


@dataclass
class UploadJob:
    """Upload job definition."""
    id: str
    content_id: str
    channel_id: str
    video_path: str
    metadata: dict[str, Any]
    priority: int = 5
    created_at: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 3
    scheduled_for: float | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content_id": self.content_id,
            "channel_id": self.channel_id,
            "video_path": self.video_path,
            "metadata": self.metadata,
            "priority": self.priority,
            "created_at": self.created_at,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "scheduled_for": self.scheduled_for,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UploadJob":
        return cls(**data)


class PriorityUploadQueue:
    """Redis-backed priority upload queue."""
    
    def __init__(self):
        self.settings = get_settings()
        self._redis = None
        self._processing = set()
    
    async def _get_redis(self):
        """Get Redis client."""
        if self._redis is None:
            self._redis = await get_redis_client()
        return self._redis
    
    def calculate_priority(
        self,
        channel_tier: str,
        virality_score: float,
        time_sensitive: bool,
        retry_count: int,
    ) -> int:
        """Calculate job priority score.
        
        Priority formula:
        - Channel tier: premium=10, standard=5, test=1 (weight: 30%)
        - Virality score: 1-10 (weight: 40%)
        - Time sensitivity: trending=10, evergreen=3 (weight: 20%)
        - Retry penalty: -1 per retry (weight: 10%)
        
        Args:
            channel_tier: Channel tier
            virality_score: Virality score 0-100
            time_sensitive: Whether content is time-sensitive
            retry_count: Number of retries
            
        Returns:
            Priority score (1-10, higher = more important)
        """
        # Channel tier (30%)
        tier_scores = {"premium": 10, "standard": 5, "test": 1}
        tier_score = tier_scores.get(channel_tier, 3) * 0.3
        
        # Virality score (40%) - normalize 0-100 to 1-10
        virality_normalized = (virality_score / 100) * 10 * 0.4
        
        # Time sensitivity (20%)
        time_score = (10 if time_sensitive else 3) * 0.2
        
        # Retry penalty (10%)
        retry_penalty = retry_count * 0.1
        
        total = tier_score + virality_normalized + time_score - retry_penalty
        
        # Clamp to 1-10
        return max(1, min(10, int(total)))
    
    async def enqueue(
        self,
        content_id: str,
        channel_id: str,
        video_path: str,
        metadata: dict[str, Any],
        priority: int | None = None,
        scheduled_for: float | None = None,
    ) -> UploadJob:
        """Add job to upload queue.
        
        Args:
            content_id: Content identifier
            channel_id: Channel identifier
            video_path: Video file path
            metadata: Upload metadata
            priority: Optional priority override
            scheduled_for: Optional scheduled time
            
        Returns:
            Created job
        """
        job_id = f"upload_{content_id}_{int(time.time() * 1000)}"
        
        # Calculate priority if not provided
        if priority is None:
            priority = self.calculate_priority(
                channel_tier=metadata.get("channel_tier", "standard"),
                virality_score=metadata.get("virality_score", 50),
                time_sensitive=metadata.get("time_sensitive", False),
                retry_count=0,
            )
        
        job = UploadJob(
            id=job_id,
            content_id=content_id,
            channel_id=channel_id,
            video_path=video_path,
            metadata=metadata,
            priority=priority,
            scheduled_for=scheduled_for,
        )
        
        redis = await self._get_redis()
        
        # Use Redis sorted set for priority queue
        # Score: negative priority (higher priority = lower score for zrange)
        # Plus timestamp for FIFO within same priority
        score = -(priority * 1000000) + job.created_at
        
        await redis.client.zadd(
            QUEUE_KEY,
            {json.dumps(job.to_dict()): score},
        )
        
        logger.info(f"Job enqueued: {job_id} (priority: {priority})")
        return job
    
    async def dequeue(self) -> UploadJob | None:
        """Get next job from queue.
        
        Returns:
            Next job or None if empty
        """
        redis = await self._get_redis()
        
        # Get job with lowest score (highest priority)
        result = await redis.client.zpopmin(QUEUE_KEY, count=1)
        
        if not result:
            return None
        
        job_data = json.loads(result[0][0])
        job = UploadJob.from_dict(job_data)
        
        # Check if scheduled for future
        if job.scheduled_for and job.scheduled_for > time.time():
            # Put back in queue
            score = -(job.priority * 1000000) + job.created_at
            await redis.client.zadd(
                QUEUE_KEY,
                {json.dumps(job.to_dict()): score},
            )
            return None
        
        # Mark as processing
        await redis.client.hset(
            PROCESSING_KEY,
            job.id,
            json.dumps({
                "started_at": time.time(),
                "job": job.to_dict(),
            }),
        )
        
        self._processing.add(job.id)
        
        logger.info(f"Job dequeued: {job.id}")
        return job
    
    async def complete_job(
        self,
        job_id: str,
        success: bool,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Mark job as completed.
        
        Args:
            job_id: Job ID
            success: Whether upload succeeded
            result: Upload result
        """
        redis = await self._get_redis()
        
        # Remove from processing
        await redis.client.hdel(PROCESSING_KEY, job_id)
        self._processing.discard(job_id)
        
        if success:
            logger.info(f"Job completed successfully: {job_id}")
        else:
            # Add to failed for retry
            await redis.client.hset(
                FAILED_KEY,
                job_id,
                json.dumps({
                    "failed_at": time.time(),
                    "result": result,
                }),
            )
            logger.warning(f"Job failed: {job_id}")
    
    async def retry_job(self, job_id: str) -> UploadJob | None:
        """Retry failed job.
        
        Args:
            job_id: Job ID to retry
            
        Returns:
            Retried job or None if max retries exceeded
        """
        redis = await self._get_redis()
        
        # Get from failed
        failed_data = await redis.client.hget(FAILED_KEY, job_id)
        if not failed_data:
            return None
        
        # Remove from failed
        await redis.client.hdel(FAILED_KEY, job_id)
        
        # Get original job
        processing_data = await redis.client.hget(PROCESSING_KEY, job_id)
        if not processing_data:
            return None
        
        data = json.loads(processing_data)
        job = UploadJob.from_dict(data["job"])
        
        # Check retry limit
        if job.retry_count >= job.max_retries:
            logger.error(f"Max retries exceeded for job: {job_id}")
            return None
        
        # Increment retry and recalculate priority
        job.retry_count += 1
        job.priority = self.calculate_priority(
            channel_tier=job.metadata.get("channel_tier", "standard"),
            virality_score=job.metadata.get("virality_score", 50),
            time_sensitive=job.metadata.get("time_sensitive", False),
            retry_count=job.retry_count,
        )
        
        # Re-enqueue with exponential backoff
        delay = min(3600, 300 * (2 ** job.retry_count))  # Max 1 hour
        job.scheduled_for = time.time() + delay
        
        score = -(job.priority * 1000000) + job.created_at
        await redis.client.zadd(
            QUEUE_KEY,
            {json.dumps(job.to_dict()): score},
        )
        
        logger.info(f"Job scheduled for retry: {job_id} (attempt {job.retry_count})")
        return job
    
    async def get_queue_status(self) -> dict[str, Any]:
        """Get queue status.
        
        Returns:
            Queue statistics
        """
        redis = await self._get_redis()
        
        pending = await redis.client.zcard(QUEUE_KEY)
        processing = await redis.client.hlen(PROCESSING_KEY)
        failed = await redis.client.hlen(FAILED_KEY)
        
        # Get priority distribution
        pending_jobs = await redis.client.zrange(QUEUE_KEY, 0, -1)
        priorities = []
        for job_json in pending_jobs[:100]:  # Sample first 100
            try:
                job = json.loads(job_json)
                priorities.append(job.get("priority", 5))
            except:
                pass
        
        avg_priority = sum(priorities) / len(priorities) if priorities else 0
        
        return {
            "pending": pending,
            "processing": processing,
            "failed": failed,
            "total": pending + processing + failed,
            "average_priority": round(avg_priority, 2),
            "priority_distribution": {
                "high": len([p for p in priorities if p >= 8]),
                "medium": len([p for p in priorities if 4 <= p < 8]),
                "low": len([p for p in priorities if p < 4]),
            },
        }
    
    async def purge_completed(self, max_age_hours: int = 24) -> int:
        """Purge old completed jobs.
        
        Args:
            max_age_hours: Maximum age in hours
            
        Returns:
            Number of purged jobs
        """
        redis = await self._get_redis()
        
        cutoff = time.time() - (max_age_hours * 3600)
        
        # Get all failed jobs
        failed = await redis.client.hgetall(FAILED_KEY)
        to_delete = []
        
        for job_id, data in failed.items():
            try:
                info = json.loads(data)
                if info.get("failed_at", 0) < cutoff:
                    to_delete.append(job_id)
            except:
                pass
        
        # Delete old entries
        if to_delete:
            await redis.client.hdel(FAILED_KEY, *to_delete)
        
        return len(to_delete)


class QueueWorker:
    """Worker to process upload queue."""
    
    def __init__(self, queue: PriorityUploadQueue):
        self.queue = queue
        self._running = False
        self._worker_id = f"worker_{int(time.time())}"
    
    async def start(self, max_concurrent: int = 3) -> None:
        """Start queue worker.
        
        Args:
            max_concurrent: Maximum concurrent uploads
        """
        self._running = True
        semaphore = asyncio.Semaphore(max_concurrent)
        
        logger.info(f"Queue worker started: {self._worker_id}")
        
        while self._running:
            try:
                async with semaphore:
                    job = await self.queue.dequeue()
                    
                    if job:
                        await self._process_job(job)
                    else:
                        # Queue empty, wait before checking again
                        await asyncio.sleep(5)
                        
            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(10)
    
    async def _process_job(self, job: UploadJob) -> None:
        """Process upload job.
        
        Args:
            job: Upload job
        """
        logger.info(f"Processing job: {job.id}")
        
        try:
            # Import here to avoid circular dependency
            from src.distributor.tasks_reels import upload_to_instagram_reels
            
            # Execute upload
            result = upload_to_instagram_reels.delay(
                video_path=job.video_path,
                metadata_json=job.metadata,
                channel_id=job.channel_id,
            )
            
            # Mark complete (Celery handles the actual work)
            await self.queue.complete_job(job.id, success=True, result={"celery_task_id": result.id})
            
        except Exception as e:
            logger.error(f"Job processing failed: {e}")
            await self.queue.complete_job(job.id, success=False, result={"error": str(e)})
            
            # Schedule retry
            await self.queue.retry_job(job.id)
    
    def stop(self) -> None:
        """Stop worker."""
        self._running = False
        logger.info(f"Queue worker stopped: {self._worker_id}")
