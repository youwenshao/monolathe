"""Channel management API endpoints."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.shared.database import get_session
from src.shared.logger import get_logger
from src.shared.models import NicheCategory
from src.shared.orm_models import ChannelORM

logger = get_logger(__name__)
router = APIRouter()


class ChannelCreateRequest(BaseModel):
    """Channel creation request."""
    name: str = Field(..., min_length=3, max_length=100)
    platform_account_id: str
    niche_category: NicheCategory
    target_demographic: dict[str, Any] = Field(default_factory=dict)
    voice_config: dict[str, Any] = Field(default_factory=dict)
    visual_config: dict[str, Any] = Field(default_factory=dict)
    posting_window: dict[str, Any] = Field(default_factory=dict)


class ChannelUpdateRequest(BaseModel):
    """Channel update request."""
    name: str | None = None
    target_demographic: dict[str, Any] | None = None
    voice_config: dict[str, Any] | None = None
    visual_config: dict[str, Any] | None = None
    posting_window: dict[str, Any] | None = None
    active: bool | None = None


@router.post(
    "/",
    response_model=dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new channel",
)
async def create_channel(request: ChannelCreateRequest) -> dict[str, Any]:
    """Create a new channel persona."""
    async with get_session() as session:
        # Check for duplicate name
        from sqlalchemy import select
        existing = await session.execute(
            select(ChannelORM).where(ChannelORM.name == request.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Channel with name '{request.name}' already exists",
            )
        
        channel = ChannelORM(
            name=request.name,
            platform_account_id=request.platform_account_id,
            niche_category=request.niche_category,
            target_demographic=request.target_demographic,
            voice_config=request.voice_config,
            visual_config=request.visual_config,
            posting_window=request.posting_window,
            active=True,
        )
        
        session.add(channel)
        await session.flush()  # Get the ID
        
        logger.info(f"Channel created: {channel.name} ({channel.id})")
        
        return {
            "id": channel.id,
            "name": channel.name,
            "niche_category": channel.niche_category.value,
            "active": channel.active,
            "created_at": channel.created_at.isoformat(),
        }


@router.get(
    "/",
    response_model=list[dict[str, Any]],
    summary="List all channels",
)
async def list_channels(
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """List all channels."""
    async with get_session() as session:
        from sqlalchemy import select
        
        query = select(ChannelORM)
        if active_only:
            query = query.where(ChannelORM.active == True)
        
        result = await session.execute(query)
        channels = result.scalars().all()
        
        return [
            {
                "id": c.id,
                "name": c.name,
                "niche_category": c.niche_category.value,
                "active": c.active,
                "last_upload_at": c.last_upload_at.isoformat() if c.last_upload_at else None,
                "created_at": c.created_at.isoformat(),
            }
            for c in channels
        ]


@router.get(
    "/{channel_id}",
    response_model=dict[str, Any],
    summary="Get channel details",
)
async def get_channel(channel_id: str) -> dict[str, Any]:
    """Get detailed information about a channel."""
    async with get_session() as session:
        channel = await session.get(ChannelORM, channel_id)
        
        if not channel:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Channel not found",
            )
        
        return {
            "id": channel.id,
            "name": channel.name,
            "niche_category": channel.niche_category.value,
            "target_demographic": channel.target_demographic,
            "voice_config": channel.voice_config,
            "visual_config": channel.visual_config,
            "posting_window": channel.posting_window,
            "active": channel.active,
            "last_upload_at": channel.last_upload_at.isoformat() if channel.last_upload_at else None,
            "created_at": channel.created_at.isoformat(),
        }


@router.patch(
    "/{channel_id}",
    response_model=dict[str, Any],
    summary="Update channel",
)
async def update_channel(
    channel_id: str,
    request: ChannelUpdateRequest,
) -> dict[str, Any]:
    """Update channel configuration."""
    async with get_session() as session:
        channel = await session.get(ChannelORM, channel_id)
        
        if not channel:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Channel not found",
            )
        
        update_data = request.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(channel, field, value)
        
        logger.info(f"Channel updated: {channel.name}")
        
        return {
            "id": channel.id,
            "name": channel.name,
            "message": "Channel updated successfully",
        }


@router.delete(
    "/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete channel",
)
async def delete_channel(channel_id: str) -> None:
    """Delete a channel (soft delete by deactivating)."""
    async with get_session() as session:
        channel = await session.get(ChannelORM, channel_id)
        
        if not channel:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Channel not found",
            )
        
        channel.active = False
        logger.info(f"Channel deactivated: {channel.name}")
