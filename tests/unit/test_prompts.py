"""Tests for prompt template manager."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.scriptforge.prompts import PromptManager, get_prompt_manager


class TestPromptManager:
    """Test cases for PromptManager class."""
    
    @pytest.fixture
    def prompt_manager(self, tmp_path):
        """Create a prompt manager with temp directory."""
        manager = PromptManager()
        manager.prompts_dir = tmp_path / "prompts"
        manager._env = None
        return manager
    
    def test_get_template_creates_default(self, prompt_manager):
        """Test that default templates are created if missing."""
        # Ensure prompts directory exists
        prompt_manager.prompts_dir.mkdir(parents=True, exist_ok=True)
        template = prompt_manager.get_template("hook_generator")
        
        assert template is not None
        assert (prompt_manager.prompts_dir / "hook_generator.j2").exists()
    
    def test_render_template(self, prompt_manager):
        """Test template rendering."""
        # Create a simple test template
        prompt_manager.prompts_dir.mkdir(parents=True, exist_ok=True)
        template_path = prompt_manager.prompts_dir / "test.j2"
        template_path.write_text("Hello {{ name }}!")
        
        rendered, version = prompt_manager.render("test", name="World")
        
        assert rendered == "Hello World!"
        assert len(version) == 16  # Hash length
    
    def test_render_with_complex_data(self, prompt_manager):
        """Test rendering with complex data types."""
        prompt_manager.prompts_dir.mkdir(parents=True, exist_ok=True)
        template_path = prompt_manager.prompts_dir / "complex.j2"
        template_path.write_text("Items: {% for item in items %}{{ item }} {% endfor %}")
        
        rendered, _ = prompt_manager.render("complex", items=["a", "b", "c"])
        
        assert "a" in rendered
        assert "b" in rendered
        assert "c" in rendered
    
    def test_version_hash_consistency(self, prompt_manager):
        """Test that same inputs produce same hash."""
        prompt_manager.prompts_dir.mkdir(parents=True, exist_ok=True)
        template_path = prompt_manager.prompts_dir / "consistent.j2"
        template_path.write_text("Test {{ var }}")
        
        _, hash1 = prompt_manager.render("consistent", var="value")
        _, hash2 = prompt_manager.render("consistent", var="value")
        
        assert hash1 == hash2
    
    def test_version_hash_changes_with_input(self, prompt_manager):
        """Test that different inputs produce different hashes."""
        prompt_manager.prompts_dir.mkdir(parents=True, exist_ok=True)
        template_path = prompt_manager.prompts_dir / "varying.j2"
        template_path.write_text("Test {{ var }}")
        
        _, hash1 = prompt_manager.render("varying", var="value1")
        _, hash2 = prompt_manager.render("varying", var="value2")
        
        assert hash1 != hash2


class TestGetPromptManager:
    """Test cases for get_prompt_manager function."""
    
    def test_singleton(self):
        """Test that get_prompt_manager returns singleton."""
        manager1 = get_prompt_manager()
        manager2 = get_prompt_manager()
        
        assert manager1 is manager2
