"""Asset generation API endpoints."""

from typing import Any, List
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.assetfactory.tasks import generate_voice, generate_image, generate_video_clip
from src.postproduction.tasks import assemble_video
from src.shared.database import get_session
from src.shared.orm_models import ScheduledContentORM
from src.shared.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

class AssetGenerateRequest(BaseModel):
    """Asset generation request."""
    script_id: str = Field(..., description="ID of the script to generate assets for")
    asset_types: List[str] = Field(..., description="List of asset types to generate (voice, image, video)")

class AssetGenerateResponse(BaseModel):
    """Asset generation response."""
    message: str
    task_ids: dict[str, str]

class PostProductionRequest(BaseModel):
    """Post-production assembly request."""
    content_id: str = Field(..., description="ID of the scheduled content to assemble")
    assets: dict[str, Any] = Field(..., description="Dictionary of asset paths (voice_path, image_paths, etc.)")
    template: str = Field(default="faceless_v1", description="Assembly template to use")

from sqlalchemy.orm import selectinload

@router.post(
    "/generate",
    response_model=AssetGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue asset generation",
)
async def queue_asset_generation(request: AssetGenerateRequest) -> AssetGenerateResponse:
    """Queue background tasks for asset generation."""
    async with get_session() as session:
        from sqlalchemy import select
        stmt = select(ScheduledContentORM).where(ScheduledContentORM.id == request.script_id).options(selectinload(ScheduledContentORM.channel))
        result = await session.execute(stmt)
        content = result.scalar_one_or_none()
        
        if not content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Script with ID {request.script_id} not found",
            )
        
        script_data = content.script_json
        channel = content.channel
        
        task_ids = {}
        
        # 1. Voice Generation
        if "voice" in request.asset_types:
            # Combine script parts for voiceover
            full_text = f"{script_data.get('hook', '')} {script_data.get('intro', '')} "
            for segment in script_data.get('body', []):
                if isinstance(segment, dict):
                    full_text += segment.get('content', '') + " "
                else:
                    # Handle case where segment might be a ScriptSegment object if parsed
                    full_text += getattr(segment, 'content', '') + " "
            full_text += script_data.get('cta', '') + " " + script_data.get('outro', '')
            
            voice_config = channel.voice_config if channel else {}
            task = generate_voice.delay(full_text, voice_config)
            task_ids["voice"] = task.id
            
        # 2. Image Generation
        if "image" in request.asset_types or "images" in request.asset_types:
            # For simplicity, generate one main image from the topic/title
            prompt = script_data.get('title', 'Cinematic background')
            visual_config = channel.visual_config if channel else {}
            task = generate_image.delay(prompt, visual_config)
            task_ids["image"] = task.id
            
        # 3. Video Assembly (Auto-trigger if assets are ready)
        # For now, let's just return the task IDs and let the user trigger assembly
        # but we could chain them here.
            
        return AssetGenerateResponse(
            message="Asset generation tasks queued. Once finished, call /assets/assemble with the generated paths.",
            task_ids=task_ids
        )

@router.post(
    "/assemble",
    response_model=dict[str, str],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue video assembly",
)
async def queue_video_assembly(request: PostProductionRequest) -> dict[str, str]:
    """Queue background task for final video assembly."""
    async with get_session() as session:
        from sqlalchemy import select
        stmt = select(ScheduledContentORM).where(ScheduledContentORM.id == request.content_id)
        result = await session.execute(stmt)
        content = result.scalar_one_or_none()
        
        if not content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Content with ID {request.content_id} not found",
            )
        
        # Queue assembly task
        task = assemble_video.delay(
            script=content.script_json,
            assets=request.assets,
            template=request.template
        )
        
        return {
            "message": "Video assembly task queued",
            "task_id": task.id
        }
