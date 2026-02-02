"""Pytest configuration and fixtures."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.shared.database import Base, get_session as get_db_session
from src.shared.models import NicheCategory, TrendSource

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client."""
    async def override_get_session():
        yield db_session
    
    app.dependency_overrides[get_db_session] = override_get_session
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()


@pytest.fixture
def sample_trend_data() -> dict[str, Any]:
    """Sample trend data for testing."""
    return {
        "id": "abc123",
        "title": "Test Trend: Something Viral Happened",
        "score": 1500,
        "num_comments": 200,
        "upvote_ratio": 0.95,
        "url": "https://reddit.com/r/test/comments/abc123",
        "subreddit": "test",
        "created_utc": 1704067200,
    }


@pytest.fixture
def sample_script_request() -> dict[str, Any]:
    """Sample script generation request."""
    return {
        "topic": "How AI is Changing Content Creation",
        "source_material": (
            "Artificial intelligence has revolutionized how we create content. "
            "From automated video editing to AI-generated scripts, creators are "
            "finding new ways to produce high-quality content faster than ever before. "
            "This trend is expected to continue growing as AI tools become more accessible."
        ),
        "audience": "content creators and digital marketers",
        "tone": "professional",
        "duration_minutes": 3.0,
        "style": "faceless",
        "niche": NicheCategory.TECHNOLOGY.value,
    }


@pytest.fixture
def sample_channel_data() -> dict[str, Any]:
    """Sample channel creation data."""
    return {
        "name": "Test Channel",
        "platform_account_id": "test_account_123",
        "niche_category": NicheCategory.TECHNOLOGY.value,
        "target_demographic": {
            "age_range": "18-34",
            "interests": ["technology", "AI", "programming"],
        },
        "voice_config": {
            "model": "f5-tts",
            "pitch": 1.0,
            "speed": 1.0,
        },
        "visual_config": {
            "lora_path": "/models/style.safetensors",
            "color_palette": ["#1a1a2e", "#16213e", "#0f3460"],
            "font_family": "Inter",
        },
        "posting_window": {
            "start_hour": 8,
            "end_hour": 20,
            "timezone": "America/New_York",
        },
    }


@pytest.fixture
def mock_deepseek_response() -> dict[str, Any]:
    """Mock DeepSeek API response."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1704067200,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '{"score": 75, "reasoning": "High engagement ratio indicates viral potential", "target_demographic": ["tech_enthusiasts"], "recommended_format": "short_form"}',
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


@pytest.fixture
def mock_script_response() -> dict[str, Any]:
    """Mock script generation response."""
    return {
        "title": "AI Content Creation Revolution",
        "hook": "What if I told you that AI could cut your editing time by 90%?",
        "intro": "Content creation is undergoing a massive shift. [VISUAL: montage of editing software]",
        "body": [
            {"segment": 1, "content": "First, let's look at automated editing tools.", "visual_notes": "Screen recording"},
            {"segment": 2, "content": "Script generation has also improved dramatically.", "visual_notes": "Text animation"},
        ],
        "cta": "Try these tools and share your results in the comments.",
        "outro": "Thanks for watching. See you in the next one.",
        "estimated_duration_minutes": 3,
        "tags": ["AI", "content creation", "productivity"],
    }
