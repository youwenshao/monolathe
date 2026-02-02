"""ScriptForge API endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.scriptforge.generator import ScriptGenerator
from src.shared.database import get_session
from src.shared.logger import get_logger
from src.shared.models import NicheCategory
from src.shared.orm_models import ScheduledContentORM

logger = get_logger(__name__)
router = APIRouter()


class ScriptGenerateRequest(BaseModel):
    """Script generation request."""
    topic: str = Field(..., min_length=10, max_length=500)
    source_material: str = Field(..., min_length=50)
    audience: str = Field(default="general")
    tone: str = Field(default="conversational")
    duration_minutes: float = Field(default=3.0, ge=1.0, le=30.0)
    style: str = Field(default="faceless")
    niche: NicheCategory = Field(default=NicheCategory.ENTERTAINMENT)
    channel_id: str | None = None


class ScriptGenerateResponse(BaseModel):
    """Script generation response."""
    message: str
    script: dict[str, Any]
    safety_check: dict[str, Any]


@router.post(
    "/generate",
    response_model=ScriptGenerateResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a video script",
)
async def generate_script(request: ScriptGenerateRequest) -> ScriptGenerateResponse:
    """Generate a complete video script from source material."""
    generator = ScriptGenerator()
    
    try:
        # Generate script
        script = await generator.generate_script(
            topic=request.topic,
            source_material=request.source_material,
            audience=request.audience,
            tone=request.tone,
            duration_minutes=request.duration_minutes,
            style=request.style,
            niche=request.niche,
        )
        
        # Run safety check
        full_text = f"{script.hook} {script.intro} " + " ".join(
            seg.content for seg in script.body
        )
        safety = await generator.safety_check(full_text, "script")
        
        if not safety["safe"] and safety["confidence"] > 0.8:
            logger.warning(f"Script failed safety check: {safety['flags']}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Script failed content safety check",
                    "flags": safety["flags"],
                    "recommendations": safety["recommendations"],
                },
            )
        
        # Store in database if channel_id provided
        if request.channel_id:
            async with get_session() as session:
                content = ScheduledContentORM(
                    channel_id=request.channel_id,
                    script_json=script.model_dump(),
                    status="drafted",
                )
                session.add(content)
                logger.info(f"Script stored for channel {request.channel_id}")
        
        return ScriptGenerateResponse(
            message="Script generated successfully",
            script=script.model_dump(),
            safety_check=safety,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Script generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Script generation failed: {str(e)}",
        )
    finally:
        await generator.close()


@router.post(
    "/hooks",
    response_model=dict[str, Any],
    summary="Generate hook variations",
)
async def generate_hooks(
    topic: str,
    tone: str = "curiosity",
    audience: str = "general",
) -> dict[str, Any]:
    """Generate multiple hook variations for A/B testing."""
    generator = ScriptGenerator()
    
    try:
        hooks = await generator.generate_hooks(topic, tone, audience)
        return {
            "topic": topic,
            "hooks": hooks,
        }
    except Exception as e:
        logger.error(f"Hook generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Hook generation failed: {str(e)}",
        )
    finally:
        await generator.close()


@router.post(
    "/seo",
    response_model=dict[str, Any],
    summary="Generate SEO metadata",
)
async def generate_seo(
    title: str,
    script_summary: str,
    keywords: list[str],
    platform: str = "youtube",
) -> dict[str, Any]:
    """Generate SEO-optimized metadata for a video."""
    generator = ScriptGenerator()
    
    try:
        metadata = await generator.generate_seo_metadata(
            title=title,
            script_summary=script_summary,
            keywords=keywords,
            platform=platform,
        )
        return metadata
    except Exception as e:
        logger.error(f"SEO generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SEO generation failed: {str(e)}",
        )
    finally:
        await generator.close()
