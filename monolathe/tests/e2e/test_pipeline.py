"""End-to-end pipeline tests.

These tests verify the complete workflow from trend discovery
to video upload. They require all services to be running.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.e2e


class TestFullPipeline:
    """End-to-end tests for the complete pipeline."""
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full infrastructure")
    async def test_trend_to_video_pipeline(self, client: AsyncClient):
        """Test complete pipeline: Trend → Script → Assets → Video → Upload."""
        # 1. Trigger trend scouting
        scout_response = await client.post(
            "/trends/scout",
            json={"source": "reddit", "limit": 5},
        )
        assert scout_response.status_code == 200
        trends = scout_response.json()["trends"]
        assert len(trends) > 0
        
        top_trend = trends[0]
        
        # 2. Create a channel
        channel_response = await client.post(
            "/channels/",
            json={
                "name": "E2E Test Channel",
                "platform_account_id": "test_account_e2e",
                "niche_category": "technology",
            },
        )
        assert channel_response.status_code == 201
        channel_id = channel_response.json()["id"]
        
        # 3. Generate script from trend
        script_response = await client.post(
            "/scripts/generate",
            json={
                "topic": top_trend["title"],
                "source_material": str(top_trend["raw_data"]),
                "audience": "tech enthusiasts",
                "duration_minutes": 2.0,
                "channel_id": channel_id,
            },
        )
        assert script_response.status_code == 200
        script_data = script_response.json()
        assert "script" in script_data
        
        # 4. Verify content was stored
        content_check = await client.get(f"/channels/{channel_id}")
        assert content_check.status_code == 200
        
        # TODO: Continue with asset generation, video assembly, and upload
        # These require the full infrastructure (Redis, Celery workers, Studio)
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires YouTube API credentials")
    async def test_youtube_upload_e2e(self, client: AsyncClient):
        """Test YouTube upload end-to-end (creates real unlisted video)."""
        # This test would create an actual unlisted video on YouTube
        # Only run in controlled test environment
        pass
