"""Trending audio matcher for Instagram Reels."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

from src.shared.config import get_settings
from src.shared.logger import get_logger
from src.shared.redis_client import get_redis_client

logger = get_logger(__name__)


@dataclass
class TrendingAudio:
    """Trending audio track information."""
    id: str
    title: str
    artist: str
    genre: str
    tempo_bpm: int
    mood: str
    trending_score: float
    platform: str
    url: str | None = None
    duration_seconds: float = 60.0
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "genre": self.genre,
            "tempo_bpm": self.tempo_bpm,
            "mood": self.mood,
            "trending_score": self.trending_score,
            "platform": self.platform,
            "url": self.url,
            "duration_seconds": self.duration_seconds,
        }


class TrendingAudioMatcher:
    """Match content to trending audio tracks."""
    
    # Genre mappings for content categories
    CATEGORY_GENRES = {
        "finance": ["corporate", "ambient", "lofi", "cinematic"],
        "technology": ["electronic", "synthwave", "ambient", "futuristic"],
        "relationships": ["lofi", "acoustic", "pop", "emotional"],
        "history": ["orchestral", "cinematic", "classical", "ambient"],
        "mystery": ["cinematic", "dark ambient", "electronic", "tension"],
    }
    
    # Mood mappings
    MOOD_MAPPINGS = {
        "excited": ["energetic", "upbeat", "happy", "motivational"],
        "calm": ["relaxed", "peaceful", "ambient", "chill"],
        "urgent": ["tense", "dramatic", "intense", "suspenseful"],
        "emotional": ["sad", "nostalgic", "romantic", "inspiring"],
    }
    
    def __init__(self):
        self.settings = get_settings()
        self._cache_key = "trending_audio"
        self._cache_ttl = 21600  # 6 hours
    
    async def fetch_trending_from_instagram(self) -> list[TrendingAudio]:
        """Fetch trending audio from Instagram API.
        
        Returns:
            List of trending audio tracks
        """
        # Instagram doesn't have a public trending audio API
        # This would require scraping or third-party service
        logger.warning("Instagram trending API not publicly available")
        return []
    
    async def fetch_trending_from_tiktok(self) -> list[TrendingAudio]:
        """Fetch trending from TikTok Creative Center.
        
        Returns:
            List of trending audio tracks
        """
        # Would require scraping TikTok Creative Center
        # or using a third-party API
        logger.warning("TikTok trending requires scraping")
        return []
    
    async def get_trending_audio(
        self,
        content_category: str,
        mood: str,
        duration: float,
        refresh: bool = False,
    ) -> list[TrendingAudio]:
        """Get trending audio matching content criteria.
        
        Args:
            content_category: Content niche
            mood: Desired mood
            duration: Video duration
            refresh: Force refresh cache
            
        Returns:
            Ranked list of matching audio tracks
        """
        # Check cache
        if not refresh:
            redis = await get_redis_client()
            cached = await redis.get_json(f"{self._cache_key}:{content_category}")
            if cached:
                return [TrendingAudio(**track) for track in cached]
        
        # Fetch from multiple sources
        all_tracks: list[TrendingAudio] = []
        
        # Source 1: Instagram (if available)
        instagram_tracks = await self.fetch_trending_from_instagram()
        all_tracks.extend(instagram_tracks)
        
        # Source 2: TikTok
        tiktok_tracks = await self.fetch_trending_from_tiktok()
        all_tracks.extend(tiktok_tracks)
        
        # Source 3: Fallback database
        fallback_tracks = self._get_fallback_tracks(content_category)
        all_tracks.extend(fallback_tracks)
        
        # Score and rank tracks
        scored_tracks = [
            (track, self._calculate_match_score(track, content_category, mood, duration))
            for track in all_tracks
        ]
        
        scored_tracks.sort(key=lambda x: x[1], reverse=True)
        
        # Return top matches
        top_tracks = [track for track, _ in scored_tracks[:10]]
        
        # Cache results
        if top_tracks:
            redis = await get_redis_client()
            await redis.set_json(
                f"{self._cache_key}:{content_category}",
                [t.to_dict() for t in top_tracks],
                expire=self._cache_ttl,
            )
        
        return top_tracks
    
    def _calculate_match_score(
        self,
        track: TrendingAudio,
        content_category: str,
        mood: str,
        duration: float,
    ) -> float:
        """Calculate how well audio matches content.
        
        Args:
            track: Audio track
            content_category: Content category
            mood: Desired mood
            duration: Video duration
            
        Returns:
            Match score (0-1)
        """
        score = 0.0
        
        # Genre match (30%)
        category_genres = self.CATEGORY_GENRES.get(content_category, [])
        if track.genre.lower() in [g.lower() for g in category_genres]:
            score += 0.3
        
        # Mood match (25%)
        mood_options = self.MOOD_MAPPINGS.get(mood, [])
        if track.mood.lower() in [m.lower() for m in mood_options]:
            score += 0.25
        
        # Duration match (25%)
        # Prefer audio slightly longer than video
        if track.duration_seconds >= duration:
            score += 0.25
        elif track.duration_seconds >= duration * 0.8:
            score += 0.15
        
        # Trending velocity (20%)
        score += track.trending_score * 0.2
        
        return score
    
    def _get_fallback_tracks(self, category: str) -> list[TrendingAudio]:
        """Get fallback tracks from local database.
        
        Args:
            category: Content category
            
        Returns:
            List of fallback tracks
        """
        # In production, load from database
        # This is a placeholder with sample data
        
        fallbacks = {
            "finance": [
                TrendingAudio(
                    id="fb_001",
                    title="Corporate Ambient",
                    artist="Stock Music",
                    genre="corporate",
                    tempo_bpm=120,
                    mood="motivational",
                    trending_score=0.8,
                    platform="fallback",
                ),
            ],
            "technology": [
                TrendingAudio(
                    id="tech_001",
                    title="Digital Future",
                    artist="Electronic Beats",
                    genre="electronic",
                    tempo_bpm=128,
                    mood="energetic",
                    trending_score=0.75,
                    platform="fallback",
                ),
            ],
        }
        
        return fallbacks.get(category, [])
    
    def suggest_audio_for_content(
        self,
        content_category: str,
        duration: float,
    ) -> dict[str, Any]:
        """Suggest audio characteristics for content.
        
        Args:
            content_category: Content niche
            duration: Video duration
            
        Returns:
            Audio suggestion
        """
        suggestions = {
            "finance": {
                "genre": "corporate",
                "tempo_range": "100-130 BPM",
                "mood": "motivational",
                "instrumentation": "piano, strings, light percussion",
            },
            "technology": {
                "genre": "electronic",
                "tempo_range": "120-140 BPM",
                "mood": "energetic",
                "instrumentation": "synth, electronic drums",
            },
            "relationships": {
                "genre": "lofi",
                "tempo_range": "80-100 BPM",
                "mood": "emotional",
                "instrumentation": "acoustic guitar, soft piano",
            },
            "mystery": {
                "genre": "cinematic",
                "tempo_range": "90-110 BPM",
                "mood": "tense",
                "instrumentation": "orchestral, dark synths",
            },
        }
        
        return {
            "category": content_category,
            "duration": duration,
            "suggestion": suggestions.get(content_category, {}),
        }
