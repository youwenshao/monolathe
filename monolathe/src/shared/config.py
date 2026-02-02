"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    secret_key: str = "change-this-in-production"

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/monolathe.db"
    database_echo: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 50

    # DeepSeek API (SiliconFlow)
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = "https://api.siliconflow.cn/v1"
    deepseek_model: str = "deepseek-ai/DeepSeek-V3"
    deepseek_timeout: float = 30.0
    deepseek_max_retries: int = 3

    # Local LLM (Ollama)
    ollama_base_url: str = "http://studio.local:11434"
    ollama_model: str = "qwen2.5:72b"

    # Reddit API
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "Monolathe/0.1.0"
    reddit_username: str = ""
    reddit_password: str = ""

    # YouTube API
    youtube_api_key: str = ""
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""

    # Instagram API
    instagram_access_token: str = ""
    instagram_business_account_id: str = ""

    # Hardware
    studio_host: str = "studio.local"
    studio_port: int = 11434
    mini_host: str = "mini.local"
    shared_storage_path: Path = Path("/Volumes/ai_content_shared")

    # Resource Limits
    max_concurrent_video_gens: int = 2
    max_concurrent_image_gens: int = 4
    max_vram_usage_gb: float = 44.0

    # Rate Limiting
    trendscout_rate_limit: int = 60
    trendscout_rate_window: int = 60
    max_uploads_per_hour: int = 3

    # Compliance
    baidu_censor_api_key: str = ""
    baidu_censor_secret: str = ""
    enable_ai_disclosure: bool = True
    enable_content_safety: bool = True

    @field_validator("shared_storage_path", mode="before")
    @classmethod
    def validate_path(cls, v: str | Path) -> Path:
        """Convert string to Path."""
        return Path(v) if isinstance(v, str) else v

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"

    @property
    def ollama_url(self) -> str:
        """Get full Ollama API URL."""
        return f"{self.ollama_base_url}/api/generate"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
