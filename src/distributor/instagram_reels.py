"""Instagram Reels distributor using Graph API.

Handles Reels-specific upload requirements, caption optimization,
and hashtag strategy for maximum reach.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from src.shared.circuit_breaker import CircuitBreakerError, create_circuit_breaker
from src.shared.config import get_settings
from src.shared.logger import get_logger
from src.shared.models_reels import InstagramReelsMetadata, PerformanceMetrics

logger = get_logger(__name__)

INSTAGRAM_GRAPH_API = "https://graph.facebook.com/v18.0"


class InstagramReelsUploader:
    """Upload videos to Instagram Reels."""
    
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None
        
        # Circuit breaker for Instagram API
        self._circuit_breaker = create_circuit_breaker(
            name="instagram_api",
            failure_threshold=3,
            recovery_timeout=300.0,  # 5 minutes
            expected_exception=(httpx.HTTPError, httpx.TimeoutException),
        )
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=30.0),
                headers={"Content-Type": "application/json"},
            )
        return self._client
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    async def _make_api_call(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make authenticated API call to Instagram Graph API.
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            data: Request body
            
        Returns:
            API response
        """
        client = await self._get_client()
        url = f"{INSTAGRAM_GRAPH_API}/{endpoint}"
        
        # Add access token
        params = params or {}
        params["access_token"] = self.settings.instagram_access_token
        
        async def _request():
            if method.upper() == "GET":
                return await client.get(url, params=params)
            elif method.upper() == "POST":
                return await client.post(url, params=params, json=data)
            else:
                raise ValueError(f"Unsupported method: {method}")
        
        try:
            response = await self._circuit_breaker.call(_request)
            response.raise_for_status()
            return response.json()
        except CircuitBreakerError:
            logger.error("Instagram API circuit breaker open")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"Instagram API error: {e.response.text}")
            raise
    
    async def upload_reel(
        self,
        video_path: str,
        metadata: InstagramReelsMetadata,
        cover_image_path: str | None = None,
    ) -> dict[str, Any]:
        """Upload video to Instagram Reels.
        
        Flow:
        1. Upload video to Instagram (resumable)
        2. Create media container
        3. Wait for processing
        4. Publish reel
        
        Args:
            video_path: Path to video file
            metadata: Reel metadata
            cover_image_path: Optional cover image
            
        Returns:
            Upload result with media ID
        """
        logger.info(f"Starting Reels upload: {metadata.caption[:50]}...")
        
        # Step 1: Initiate upload session
        upload_session = await self._initiate_upload(video_path)
        
        # Step 2: Upload video chunks
        await self._upload_video_chunks(video_path, upload_session)
        
        # Step 3: Create media container
        media_container = await self._create_media_container(
            upload_session["upload_url"],
            metadata,
            cover_image_path,
        )
        
        # Step 4: Wait for processing
        media_id = await self._wait_for_processing(media_container["id"])
        
        # Step 5: Publish (if not scheduled)
        if not metadata.scheduled_publish:
            publish_result = await self._publish_reel(media_id)
            logger.info(f"Reel published: {publish_result.get('id')}")
            return publish_result
        
        return {"media_id": media_id, "status": "scheduled"}
    
    async def _initiate_upload(self, video_path: str) -> dict[str, Any]:
        """Initiate resumable upload session.
        
        Args:
            video_path: Video file path
            
        Returns:
            Upload session info
        """
        file_size = Path(video_path).stat().st_size
        
        params = {
            "upload_phase": "start",
            "file_size": file_size,
        }
        
        result = await self._make_api_call(
            "POST",
            f"{self.settings.instagram_business_account_id}/media",
            params=params,
        )
        
        logger.debug(f"Upload initiated: {result.get('upload_session_id')}")
        return result
    
    async def _upload_video_chunks(
        self,
        video_path: str,
        session: dict[str, Any],
        chunk_size: int = 5 * 1024 * 1024,  # 5MB chunks
    ) -> None:
        """Upload video in chunks.
        
        Args:
            video_path: Video file path
            session: Upload session info
            chunk_size: Chunk size in bytes
        """
        file_size = Path(video_path).stat().st_size
        start_offset = 0
        
        with open(video_path, "rb") as f:
            while start_offset < file_size:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                
                params = {
                    "upload_phase": "transfer",
                    "upload_session_id": session["upload_session_id"],
                    "start_offset": start_offset,
                }
                
                # Upload chunk
                client = await self._get_client()
                files = {"video_file_chunk": ("chunk", chunk, "video/mp4")}
                
                await self._circuit_breaker.call(
                    lambda: client.post(
                        f"{INSTAGRAM_GRAPH_API}/{self.settings.instagram_business_account_id}/media",
                        params={**params, "access_token": self.settings.instagram_access_token},
                        files=files,
                    )
                )
                
                start_offset += len(chunk)
                logger.debug(f"Uploaded chunk: {start_offset}/{file_size}")
        
        # Finish upload
        await self._make_api_call(
            "POST",
            f"{self.settings.instagram_business_account_id}/media",
            params={
                "upload_phase": "finish",
                "upload_session_id": session["upload_session_id"],
            },
        )
        
        logger.info("Video upload completed")
    
    async def _create_media_container(
        self,
        video_url: str,
        metadata: InstagramReelsMetadata,
        cover_image_path: str | None,
    ) -> dict[str, Any]:
        """Create media container for Reel.
        
        Args:
            video_url: Uploaded video URL
            metadata: Reel metadata
            cover_image_path: Cover image path
            
        Returns:
            Media container info
        """
        params: dict[str, Any] = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": metadata.caption_with_hashtags[:2200],
            "share_to_feed": metadata.share_to_feed,
        }
        
        # Upload cover image if provided
        if cover_image_path and Path(cover_image_path).exists():
            cover_url = await self._upload_cover_image(cover_image_path)
            params["cover_url"] = cover_url
        
        # Add audio attribution
        if metadata.audio_attribution:
            params["audio_name"] = metadata.audio_attribution
        
        result = await self._make_api_call(
            "POST",
            f"{self.settings.instagram_business_account_id}/media",
            params=params,
        )
        
        logger.info(f"Media container created: {result.get('id')}")
        return result
    
    async def _upload_cover_image(self, image_path: str) -> str:
        """Upload cover image.
        
        Args:
            image_path: Image file path
            
        Returns:
            Uploaded image URL
        """
        # Simplified - in production, use proper image upload
        return f"file://{image_path}"
    
    async def _wait_for_processing(
        self,
        media_id: str,
        max_attempts: int = 30,
        delay: float = 5.0,
    ) -> str:
        """Wait for video processing to complete.
        
        Args:
            media_id: Media container ID
            max_attempts: Maximum status checks
            delay: Delay between checks
            
        Returns:
            Final media ID
        """
        for attempt in range(max_attempts):
            result = await self._make_api_call(
                "GET",
                media_id,
                params={"fields": "status,status_code"},
            )
            
            status = result.get("status")
            
            if status == "FINISHED":
                logger.info(f"Processing complete: {media_id}")
                return media_id
            elif status == "ERROR":
                error = result.get("status_code", "Unknown error")
                logger.error(f"Processing failed: {error}")
                raise RuntimeError(f"Instagram processing failed: {error}")
            
            logger.debug(f"Processing status: {status}, attempt {attempt + 1}")
            await asyncio.sleep(delay)
        
        raise TimeoutError("Processing timeout")
    
    async def _publish_reel(self, media_id: str) -> dict[str, Any]:
        """Publish the Reel.
        
        Args:
            media_id: Media ID to publish
            
        Returns:
            Publish result
        """
        result = await self._make_api_call(
            "POST",
            f"{self.settings.instagram_business_account_id}/media_publish",
            params={"creation_id": media_id},
        )
        
        return result
    
    async def get_performance_metrics(
        self,
        media_id: str,
        content_id: str,
    ) -> PerformanceMetrics:
        """Get performance metrics for published Reel.
        
        Args:
            media_id: Instagram media ID
            content_id: Internal content ID
            
        Returns:
            Performance metrics
        """
        fields = [
            "views",
            "likes",
            "comments",
            "shares",
            "saved",
            "reach",
            "engagement",
        ]
        
        result = await self._make_api_call(
            "GET",
            media_id,
            params={"fields": ",".join(fields)},
        )
        
        return PerformanceMetrics(
            content_id=content_id,
            platform="instagram",
            media_id=media_id,
            views=result.get("views", 0),
            likes=result.get("likes", 0),
            comments=result.get("comments", 0),
            shares=result.get("shares", 0),
            saves=result.get("saved", 0),
            reach=result.get("reach", 0),
            engagement_rate=result.get("engagement", 0),
        )
    
    def optimize_hashtags(
        self,
        niche: str,
        trending: list[str] | None = None,
        max_tags: int = 30,
    ) -> list[str]:
        """Generate optimized hashtag set.
        
        Strategy:
        - 3-5 broad high-volume tags
        - 10-15 niche-specific tags
        - 5-10 trending tags
        - 3-5 branded/unique tags
        
        Args:
            niche: Content niche
            trending: List of trending hashtags
            max_tags: Maximum hashtags
            
        Returns:
            Optimized hashtag list
        """
        # Base hashtags by niche
        base_tags = {
            "finance": [
                "personalfinance", "moneytips", "financialeducation",
                "investing", "wealthbuilding", "budgeting",
            ],
            "technology": [
                "tech", "technology", "ai", "artificialintelligence",
                "innovation", "techtok",
            ],
            "relationships": [
                "relationshipadvice", "dating", "relationshiptips",
                "love", "couples", "relationshiptok",
            ],
            "history": [
                "history", "historical", "historytok", "learnhistory",
                "archaeology", "ancienthistory",
            ],
            "mystery": [
                "unsolved", "mystery", "truecrime", "unsolvedmysteries",
                "crime", "investigation",
            ],
        }
        
        # Broad high-volume tags
        broad = ["fyp", "foryou", "viral", "trending", "reels"]
        
        # Niche tags
        niche_tags = base_tags.get(niche.lower(), ["content", "video", "viral"])
        
        # Trending tags
        trending = trending or []
        
        # Combine and deduplicate
        all_tags = broad[:3] + niche_tags + trending[:10]
        
        # Remove duplicates while preserving order
        seen = set()
        unique_tags = []
        for tag in all_tags:
            tag_clean = tag.lstrip("#").lower()
            if tag_clean not in seen and len(unique_tags) < max_tags:
                seen.add(tag_clean)
                unique_tags.append(tag_clean)
        
        return unique_tags
    
    def generate_caption(
        self,
        hook: str,
        body: str,
        cta: str,
        hashtags: list[str],
        max_length: int = 2200,
    ) -> str:
        """Generate optimized caption for Reels.
        
        Args:
            hook: Opening hook
            body: Main caption body
            cta: Call to action
            hashtags: Hashtag list
            max_length: Maximum caption length
            
        Returns:
            Formatted caption
        """
        # Build caption
        parts = [
            hook,
            "",
            body,
            "",
            cta,
            "",
        ]
        
        caption = "\n".join(parts)
        
        # Add hashtags if space permits
        hashtag_str = " ".join(f"#{tag}" for tag in hashtags)
        if len(caption) + len(hashtag_str) + 2 <= max_length:
            caption += hashtag_str
        else:
            # Truncate hashtags
            available = max_length - len(caption) - 2
            truncated_tags = []
            current_len = 0
            for tag in hashtags:
                tag_str = f"#{tag} "
                if current_len + len(tag_str) <= available:
                    truncated_tags.append(tag)
                    current_len += len(tag_str)
            caption += " ".join(f"#{tag}" for tag in truncated_tags)
        
        return caption[:max_length]


class TrendingAudioMatcher:
    """Match trending audio to content."""
    
    def __init__(self) -> None:
        self.settings = get_settings()
    
    async def get_trending_audio(
        self,
        genre: str | None = None,
        mood: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get trending audio from Instagram.
        
        Args:
            genre: Music genre filter
            mood: Mood filter
            
        Returns:
            List of trending audio tracks
        """
        # TODO: Implement Instagram trending audio API
        # For now, return placeholder
        logger.warning("Trending audio API not implemented")
        return []
    
    def suggest_audio(
        self,
        content_category: str,
        duration: float,
    ) -> dict[str, Any]:
        """Suggest audio based on content.
        
        Args:
            content_category: Content type
            duration: Video duration
            
        Returns:
            Audio suggestion
        """
        suggestions = {
            "finance": {
                "genre": "ambient_corporate",
                "tempo": "medium",
                "energy": "low",
            },
            "technology": {
                "genre": "electronic",
                "tempo": "medium_fast",
                "energy": "medium",
            },
            "relationships": {
                "genre": "lofi",
                "tempo": "slow",
                "energy": "low",
            },
            "mystery": {
                "genre": "cinematic",
                "tempo": "slow",
                "energy": "high",
            },
        }
        
        return suggestions.get(content_category.lower(), {
            "genre": "pop",
            "tempo": "medium",
            "energy": "medium",
        })
