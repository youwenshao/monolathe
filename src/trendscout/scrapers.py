"""Web scrapers for trend data sources."""

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import aiohttp
import praw
from praw.models import Submission

from src.shared.config import get_settings
from src.shared.logger import get_logger
from src.shared.models import TrendSource

logger = get_logger(__name__)


class BaseScraper(ABC):
    """Base class for trend scrapers."""
    
    def __init__(self, source: TrendSource) -> None:
        self.source = source
        self.settings = get_settings()
    
    @abstractmethod
    async def scrape(self, limit: int = 25) -> list[dict[str, Any]]:
        """Scrape trends from source.
        
        Args:
            limit: Maximum number of items to scrape
            
        Returns:
            List of raw trend data
        """
        pass


class RedditScraper(BaseScraper):
    """Reddit scraper using PRAW."""
    
    TARGET_SUBREDDITS = [
        "relationship_advice",
        "technology",
        "personalfinance",
        "AskReddit",
        "funny",
        "todayilearned",
        "LifeProTips",
    ]
    
    def __init__(self) -> None:
        super().__init__(TrendSource.REDDIT)
        self._reddit: praw.Reddit | None = None
    
    def _get_client(self) -> praw.Reddit:
        """Get or create Reddit client."""
        if self._reddit is None:
            self._reddit = praw.Reddit(
                client_id=self.settings.reddit_client_id,
                client_secret=self.settings.reddit_client_secret,
                user_agent=self.settings.reddit_user_agent,
                username=self.settings.reddit_username,
                password=self.settings.reddit_password,
            )
        return self._reddit
    
    def _submission_to_dict(self, submission: Submission) -> dict[str, Any]:
        """Convert submission to dictionary."""
        return {
            "id": submission.id,
            "title": submission.title,
            "score": submission.score,
            "upvote_ratio": submission.upvote_ratio,
            "num_comments": submission.num_comments,
            "url": f"https://reddit.com{submission.permalink}",
            "subreddit": submission.subreddit.display_name,
            "created_utc": submission.created_utc,
            "is_video": submission.is_video,
            "over_18": submission.over_18,
            "spoiler": submission.spoiler,
        }
    
    async def scrape(self, limit: int = 25) -> list[dict[str, Any]]:
        """Scrape hot posts from target subreddits."""
        reddit = self._get_client()
        results = []
        
        # Run blocking PRAW calls in thread pool
        loop = asyncio.get_event_loop()
        
        for subreddit_name in self.TARGET_SUBREDDITS:
            try:
                subreddit = await loop.run_in_executor(
                    None, reddit.subreddit, subreddit_name
                )
                hot_posts = await loop.run_in_executor(
                    None, lambda: list(subreddit.hot(limit=limit // len(self.TARGET_SUBREDDITS)))
                )
                
                for submission in hot_posts:
                    # Skip stickied posts and low engagement
                    if submission.stickied or submission.score < 100:
                        continue
                    
                    data = self._submission_to_dict(submission)
                    data["_scraped_at"] = datetime.utcnow().isoformat()
                    results.append(data)
                
                logger.debug(f"Scraped {len(hot_posts)} posts from r/{subreddit_name}")
                
            except Exception as e:
                logger.error(f"Error scraping r/{subreddit_name}: {e}")
                continue
        
        logger.info(f"Reddit scraper collected {len(results)} trends")
        return results


class YouTubeScraper(BaseScraper):
    """YouTube trending scraper using yt-dlp and unofficial APIs."""
    
    TRENDING_CATEGORIES = ["default", "music", "gaming", "movies"]
    
    def __init__(self) -> None:
        super().__init__(TrendSource.YOUTUBE)
        self._session: aiohttp.ClientSession | None = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                }
            )
        return self._session
    
    async def scrape(self, limit: int = 25) -> list[dict[str, Any]]:
        """Scrape trending videos from YouTube."""
        results = []
        
        try:
            # Use yt-dlp to get trending videos
            import yt_dlp
            
            ydl_opts = {
                "quiet": True,
                "extract_flat": True,
                "playlistend": limit,
            }
            
            loop = asyncio.get_event_loop()
            
            for category in self.TRENDING_CATEGORIES[:1]:  # Just default for rate limiting
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        playlist_url = f"ytsearch{limit}:trending now"
                        info = await loop.run_in_executor(
                            None, ydl.extract_info, playlist_url, False
                        )
                        
                        if info and "entries" in info:
                            for entry in info["entries"]:
                                if entry:
                                    results.append({
                                        "id": entry.get("id"),
                                        "title": entry.get("title"),
                                        "url": entry.get("url"),
                                        "duration": entry.get("duration"),
                                        "view_count": entry.get("view_count"),
                                        "channel": entry.get("channel"),
                                        "category": category,
                                        "_scraped_at": datetime.utcnow().isoformat(),
                                    })
                    
                except Exception as e:
                    logger.error(f"Error scraping YouTube trending: {e}")
                    continue
            
        except ImportError:
            logger.warning("yt-dlp not installed, using fallback method")
            # Fallback: return empty list
            pass
        
        logger.info(f"YouTube scraper collected {len(results)} trends")
        return results


class GoogleTrendsScraper(BaseScraper):
    """Google Trends scraper using pytrends."""
    
    def __init__(self) -> None:
        super().__init__(TrendSource.GOOGLE_TRENDS)
    
    async def scrape(self, limit: int = 25) -> list[dict[str, Any]]:
        """Scrape trending searches from Google Trends."""
        results = []
        
        try:
            from pytrends.request import TrendReq
            
            pytrends = TrendReq(hl="en-US", tz=480)  # HKT timezone
            
            loop = asyncio.get_event_loop()
            trending = await loop.run_in_executor(
                None, pytrends.trending_searches, "united_states"
            )
            
            if trending is not None and not trending.empty:
                for idx, row in trending.head(limit).iterrows():
                    results.append({
                        "rank": idx + 1,
                        "title": row[0],
                        "source": "google_trends",
                        "_scraped_at": datetime.utcnow().isoformat(),
                    })
            
        except ImportError:
            logger.warning("pytrends not installed")
        except Exception as e:
            logger.error(f"Error scraping Google Trends: {e}")
        
        logger.info(f"Google Trends scraper collected {len(results)} trends")
        return results


class ScraperManager:
    """Manager for all trend scrapers."""
    
    def __init__(self) -> None:
        self.scrapers: dict[TrendSource, BaseScraper] = {
            TrendSource.REDDIT: RedditScraper(),
            TrendSource.YOUTUBE: YouTubeScraper(),
            TrendSource.GOOGLE_TRENDS: GoogleTrendsScraper(),
        }
    
    async def scrape_all(self, limit_per_source: int = 25) -> dict[TrendSource, list[dict[str, Any]]]:
        """Scrape all configured sources.
        
        Args:
            limit_per_source: Maximum items per source
            
        Returns:
            Dictionary mapping sources to their scraped data
        """
        results: dict[TrendSource, list[dict[str, Any]]] = {}
        
        for source, scraper in self.scrapers.items():
            try:
                data = await scraper.scrape(limit=limit_per_source)
                results[source] = data
            except Exception as e:
                logger.error(f"Scraper {source.value} failed: {e}")
                results[source] = []
        
        total = sum(len(v) for v in results.values())
        logger.info(f"ScraperManager collected {total} total trends from {len(results)} sources")
        return results
    
    async def scrape_source(
        self,
        source: TrendSource,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Scrape a specific source."""
        scraper = self.scrapers.get(source)
        if not scraper:
            raise ValueError(f"No scraper configured for source: {source}")
        return await scraper.scrape(limit=limit)
