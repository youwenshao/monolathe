"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from src.shared.models import (
    ContentStatus,
    NicheCategory,
    Platform,
    TrendSource,
    ViralityScore,
    VideoScript,
    ScriptSegment,
)


class TestViralityScore:
    """Test cases for ViralityScore model."""
    
    def test_valid_score(self):
        """Test valid virality score."""
        score = ViralityScore(
            score=75,
            reasoning="High engagement",
            target_demographic=["tech_enthusiasts"],
        )
        assert score.score == 75
    
    def test_score_bounds(self):
        """Test score boundaries."""
        with pytest.raises(ValidationError):
            ViralityScore(score=101, reasoning="Too high")
        
        with pytest.raises(ValidationError):
            ViralityScore(score=-1, reasoning="Too low")
    
    def test_default_values(self):
        """Test default values."""
        score = ViralityScore(score=50, reasoning="Average")
        assert score.target_demographic == []
        assert score.recommended_format == "short_form"


class TestVideoScript:
    """Test cases for VideoScript model."""
    
    def test_valid_script(self):
        """Test valid video script creation."""
        script = VideoScript(
            title="Test Video",
            hook="Attention grabber",
            intro="Introduction here",
            body=[
                ScriptSegment(type="body", content="First segment"),
                ScriptSegment(type="body", content="Second segment"),
            ],
            cta="Subscribe now",
        )
        
        assert script.title == "Test Video"
        assert len(script.body) == 2
        assert script.category == "entertainment"  # default
    
    def test_script_serialization(self):
        """Test script serialization."""
        script = VideoScript(
            title="Test",
            hook="Hook",
            intro="Intro",
            body=[ScriptSegment(type="body", content="Content")],
            cta="CTA",
            tags=["tag1", "tag2"],
        )
        
        data = script.model_dump()
        assert data["title"] == "Test"
        assert data["tags"] == ["tag1", "tag2"]


class TestEnums:
    """Test cases for enum classes."""
    
    def test_content_status_values(self):
        """Test ContentStatus enum values."""
        assert ContentStatus.DRAFTED.value == "drafted"
        assert ContentStatus.PUBLISHED.value == "published"
        assert ContentStatus.FAILED.value == "failed"
    
    def test_platform_values(self):
        """Test Platform enum values."""
        assert Platform.YOUTUBE.value == "youtube"
        assert Platform.INSTAGRAM.value == "instagram"
    
    def test_niche_category_values(self):
        """Test NicheCategory enum values."""
        assert NicheCategory.FINANCE.value == "finance"
        assert NicheCategory.TECHNOLOGY.value == "technology"
    
    def test_trend_source_values(self):
        """Test TrendSource enum values."""
        assert TrendSource.REDDIT.value == "reddit"
        assert TrendSource.YOUTUBE.value == "youtube"
