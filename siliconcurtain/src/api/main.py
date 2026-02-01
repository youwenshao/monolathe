"""FastAPI application factory and lifespan management."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routers import channels, health, scripts, trends
from src.shared.config import get_settings
from src.shared.database import close_db, init_db
from src.shared.logger import get_logger, setup_logging
from src.shared.redis_client import close_redis, get_redis_client
from src.trendscout.scheduler import TrendScoutScheduler

logger = get_logger(__name__)

# Global scheduler instance
_trend_scheduler: TrendScoutScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    # Startup
    setup_logging()
    logger.info("Starting SiliconCurtain API...")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    # Connect to Redis
    await get_redis_client()
    logger.info("Redis connected")
    
    # Start trend scheduler
    global _trend_scheduler
    _trend_scheduler = TrendScoutScheduler()
    _trend_scheduler.start()
    logger.info("Trend scheduler started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down SiliconCurtain API...")
    
    if _trend_scheduler:
        _trend_scheduler.shutdown()
    
    await close_redis()
    await close_db()
    
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()
    
    app = FastAPI(
        title="SiliconCurtain API",
        description="AI Content Automation Pipeline",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(trends.router, prefix="/trends", tags=["TrendScout"])
    app.include_router(scripts.router, prefix="/scripts", tags=["ScriptForge"])
    app.include_router(channels.router, prefix="/channels", tags=["Channels"])
    
    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
    
    return app


# Create app instance
app = create_app()
