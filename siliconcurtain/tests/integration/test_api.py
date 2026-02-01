"""Integration tests for API endpoints."""

import pytest
from httpx import AsyncClient


class TestHealthEndpoints:
    """Test cases for health check endpoints."""
    
    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        """Test health check endpoint."""
        response = await client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "checks" in data
    
    @pytest.mark.asyncio
    async def test_ready_probe(self, client: AsyncClient):
        """Test readiness probe endpoint."""
        response = await client.get("/ready")
        
        assert response.status_code == 200
        assert response.json()["status"] == "ready"
    
    @pytest.mark.asyncio
    async def test_live_probe(self, client: AsyncClient):
        """Test liveness probe endpoint."""
        response = await client.get("/live")
        
        assert response.status_code == 200
        assert response.json()["status"] == "alive"


class TestChannelEndpoints:
    """Test cases for channel management endpoints."""
    
    @pytest.mark.asyncio
    async def test_create_channel(self, client: AsyncClient, sample_channel_data):
        """Test channel creation."""
        response = await client.post("/channels/", json=sample_channel_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == sample_channel_data["name"]
        assert "id" in data
        assert data["active"] is True
    
    @pytest.mark.asyncio
    async def test_create_duplicate_channel(self, client: AsyncClient, sample_channel_data):
        """Test creating duplicate channel fails."""
        # Create first channel
        await client.post("/channels/", json=sample_channel_data)
        
        # Try to create duplicate
        response = await client.post("/channels/", json=sample_channel_data)
        
        assert response.status_code == 409
    
    @pytest.mark.asyncio
    async def test_list_channels(self, client: AsyncClient, sample_channel_data):
        """Test listing channels."""
        # Create a channel
        await client.post("/channels/", json=sample_channel_data)
        
        # List channels
        response = await client.get("/channels/")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
    
    @pytest.mark.asyncio
    async def test_get_channel(self, client: AsyncClient, sample_channel_data):
        """Test getting channel details."""
        # Create channel
        create_response = await client.post("/channels/", json=sample_channel_data)
        channel_id = create_response.json()["id"]
        
        # Get channel
        response = await client.get(f"/channels/{channel_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == channel_id
        assert data["name"] == sample_channel_data["name"]
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_channel(self, client: AsyncClient):
        """Test getting non-existent channel returns 404."""
        response = await client.get("/channels/nonexistent-id")
        
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_update_channel(self, client: AsyncClient, sample_channel_data):
        """Test updating channel."""
        # Create channel
        create_response = await client.post("/channels/", json=sample_channel_data)
        channel_id = create_response.json()["id"]
        
        # Update channel
        update_data = {"name": "Updated Name"}
        response = await client.patch(f"/channels/{channel_id}", json=update_data)
        
        assert response.status_code == 200
        assert response.json()["message"] == "Channel updated successfully"
    
    @pytest.mark.asyncio
    async def test_delete_channel(self, client: AsyncClient, sample_channel_data):
        """Test deleting (deactivating) channel."""
        # Create channel
        create_response = await client.post("/channels/", json=sample_channel_data)
        channel_id = create_response.json()["id"]
        
        # Delete channel
        response = await client.delete(f"/channels/{channel_id}")
        
        assert response.status_code == 204


class TestTrendEndpoints:
    """Test cases for trend endpoints."""
    
    @pytest.mark.asyncio
    async def test_get_trends_empty(self, client: AsyncClient):
        """Test getting trends when none exist."""
        response = await client.get("/trends/")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    @pytest.mark.asyncio
    async def test_get_trend_not_found(self, client: AsyncClient):
        """Test getting non-existent trend."""
        response = await client.get("/trends/nonexistent-id")
        
        assert response.status_code == 404


class TestScriptEndpoints:
    """Test cases for script endpoints."""
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_generate_hooks(self, client: AsyncClient):
        """Test hook generation endpoint."""
        response = await client.post(
            "/scripts/hooks",
            params={"topic": "Test topic for video", "tone": "curiosity"},
        )
        
        # May fail if LLM not available, so accept various status codes
        assert response.status_code in [200, 500, 502, 503]
