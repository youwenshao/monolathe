"""Tests for configuration module."""

import pytest
from pydantic import ValidationError

from src.shared.config import Settings, get_settings


class TestSettings:
    """Test cases for Settings class."""
    
    def test_default_settings(self):
        """Test default settings values."""
        settings = Settings()
        
        assert settings.environment == "development"
        assert settings.debug is False
        assert settings.log_level == "INFO"
        assert settings.deepseek_base_url == "https://api.deepseek.com"
        assert settings.deepseek_model == "deepseek-chat"
    
    def test_is_production(self):
        """Test production environment detection."""
        dev_settings = Settings(environment="development")
        prod_settings = Settings(environment="production")
        
        assert dev_settings.is_production is False
        assert prod_settings.is_production is True
    
    def test_ollama_url(self):
        """Test Ollama URL construction."""
        settings = Settings(ollama_base_url="http://localhost:11434")
        assert settings.ollama_url == "http://localhost:11434/api/generate"
    
    def test_path_validation(self):
        """Test path field validation."""
        settings = Settings(shared_storage_path="/tmp/test")
        assert str(settings.shared_storage_path) == "/tmp/test"
    
    def test_invalid_environment(self):
        """Test invalid environment value."""
        with pytest.raises(ValidationError):
            Settings(environment="invalid")


class TestGetSettings:
    """Test cases for get_settings function."""
    
    def test_cached_settings(self):
        """Test that settings are cached."""
        settings1 = get_settings()
        settings2 = get_settings()
        
        # Should be same object due to lru_cache
        assert settings1 is settings2
