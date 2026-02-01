"""Instagram OAuth2 manager with token refresh."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select

from src.shared.config import get_settings
from src.shared.database import get_session
from src.shared.logger import get_logger
from src.shared.orm_models import ChannelORM

logger = get_logger(__name__)

INSTAGRAM_AUTH_URL = "https://www.facebook.com/v18.0/dialog/oauth"
INSTAGRAM_TOKEN_URL = "https://graph.facebook.com/v18.0/oauth/access_token"


class InstagramOAuthManager:
    """Manage Instagram OAuth2 flow and token refresh."""
    
    def __init__(self):
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None
        self._token_cache: dict[str, dict[str, Any]] = {}
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    def get_authorization_url(
        self,
        channel_id: str,
        redirect_uri: str,
        scope: list[str] | None = None,
    ) -> str:
        """Generate authorization URL for OAuth flow.
        
        Args:
            channel_id: Channel being authorized
            redirect_uri: OAuth redirect URI
            scope: Permission scopes
            
        Returns:
            Authorization URL
        """
        scope = scope or [
            "instagram_basic",
            "instagram_content_publish",
            "instagram_manage_insights",
        ]
        
        params = {
            "client_id": self.settings.instagram_client_id,
            "redirect_uri": redirect_uri,
            "scope": ",".join(scope),
            "response_type": "code",
            "state": channel_id,  # CSRF protection
        }
        
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{INSTAGRAM_AUTH_URL}?{query}"
    
    async def exchange_code_for_token(
        self,
        code: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        """Exchange authorization code for access token.
        
        Args:
            code: Authorization code
            redirect_uri: Redirect URI
            
        Returns:
            Token response
        """
        client = await self._get_client()
        
        params = {
            "client_id": self.settings.instagram_client_id,
            "client_secret": self.settings.instagram_client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        
        response = await client.get(INSTAGRAM_TOKEN_URL, params=params)
        response.raise_for_status()
        
        token_data = response.json()
        
        # Calculate expiry
        expires_in = token_data.get("expires_in", 3600)
        token_data["expires_at"] = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()
        
        logger.info("OAuth token obtained successfully")
        return token_data
    
    async def refresh_access_token(
        self,
        refresh_token: str,
    ) -> dict[str, Any]:
        """Refresh expired access token.
        
        Args:
            refresh_token: Refresh token
            
        Returns:
            New token data
        """
        client = await self._get_client()
        
        params = {
            "client_id": self.settings.instagram_client_id,
            "client_secret": self.settings.instagram_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        
        response = await client.get(INSTAGRAM_TOKEN_URL, params=params)
        response.raise_for_status()
        
        token_data = response.json()
        
        expires_in = token_data.get("expires_in", 3600)
        token_data["expires_at"] = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()
        
        logger.info("OAuth token refreshed successfully")
        return token_data
    
    async def get_valid_token(self, channel_id: str) -> str:
        """Get valid access token for channel, refreshing if needed.
        
        Args:
            channel_id: Channel ID
            
        Returns:
            Valid access token
        """
        # Check cache first
        cached = self._token_cache.get(channel_id)
        if cached:
            expires_at = datetime.fromisoformat(cached["expires_at"])
            if expires_at > datetime.utcnow() + timedelta(minutes=5):
                return cached["access_token"]
        
        # Get from database
        async with get_session() as session:
            result = await session.execute(
                select(ChannelORM).where(ChannelORM.id == channel_id)
            )
            channel = result.scalar_one_or_none()
            
            if not channel:
                raise ValueError(f"Channel {channel_id} not found")
            
            # Get token from channel config
            token_data = channel.voice_config.get("instagram_token", {})
            
            if not token_data:
                raise ValueError(f"No token found for channel {channel_id}")
            
            expires_at = datetime.fromisoformat(token_data.get("expires_at", "2000-01-01"))
            
            # Refresh if expiring soon
            if expires_at < datetime.utcnow() + timedelta(minutes=5):
                logger.info(f"Refreshing token for channel {channel_id}")
                new_token = await self.refresh_access_token(
                    token_data["refresh_token"]
                )
                
                # Update database
                channel.voice_config["instagram_token"] = new_token
                await session.commit()
                
                # Update cache
                self._token_cache[channel_id] = new_token
                return new_token["access_token"]
            
            # Update cache
            self._token_cache[channel_id] = token_data
            return token_data["access_token"]
    
    async def revoke_token(self, channel_id: str) -> bool:
        """Revoke OAuth token for channel.
        
        Args:
            channel_id: Channel ID
            
        Returns:
            True if revoked successfully
        """
        try:
            token = await self.get_valid_token(channel_id)
            
            client = await self._get_client()
            
            # Instagram doesn't have a standard revoke endpoint
            # Token is invalidated by removing from our storage
            
            async with get_session() as session:
                result = await session.execute(
                    select(ChannelORM).where(ChannelORM.id == channel_id)
                )
                channel = result.scalar_one_or_none()
                
                if channel and "instagram_token" in channel.voice_config:
                    del channel.voice_config["instagram_token"]
                    await session.commit()
            
            # Clear cache
            self._token_cache.pop(channel_id, None)
            
            logger.info(f"Token revoked for channel {channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Token revocation failed: {e}")
            return False
    
    def is_token_valid(self, channel_id: str) -> bool:
        """Check if channel has valid token.
        
        Args:
            channel_id: Channel ID
            
        Returns:
            True if token is valid
        """
        cached = self._token_cache.get(channel_id)
        if not cached:
            return False
        
        try:
            expires_at = datetime.fromisoformat(cached["expires_at"])
            return expires_at > datetime.utcnow() + timedelta(minutes=5)
        except (KeyError, ValueError):
            return False
