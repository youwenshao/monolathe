"""Jinja2 prompt templates for content generation."""

import hashlib
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, Template

from src.shared.config import get_settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


class PromptManager:
    """Manager for Jinja2 prompt templates."""
    
    def __init__(self) -> None:
        self.settings = get_settings()
        self.prompts_dir = Path(__file__).parent.parent.parent / "config" / "prompts"
        self._env: Environment | None = None
        self._cache: dict[str, tuple[Template, str]] = {}
    
    def _get_env(self) -> Environment:
        """Get or create Jinja2 environment."""
        if self._env is None:
            # Create prompts directory if it doesn't exist
            self.prompts_dir.mkdir(parents=True, exist_ok=True)
            
            self._env = Environment(
                loader=FileSystemLoader(self.prompts_dir),
                auto_reload=self.settings.debug,
            )
        return self._env
    
    def _get_template_hash(self, content: str) -> str:
        """Generate hash for template content."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def get_template(self, name: str) -> Template:
        """Get a template by name.
        
        Args:
            name: Template name without extension (e.g., "hook_generator")
            
        Returns:
            Jinja2 Template instance
        """
        template_path = self.prompts_dir / f"{name}.j2"
        
        # Check if template exists, create default if not
        if not template_path.exists():
            self._create_default_template(name, template_path)
        
        return self._get_env().get_template(f"{name}.j2")
    
    def _create_default_template(self, name: str, path: Path) -> None:
        """Create a default template if it doesn't exist."""
        templates = {
            "hook_generator": """You are an expert at writing viral video hooks.
Create 3 attention-grabbing hooks for a video about: {{ topic }}

The hooks should:
- Be under 10 seconds when spoken
- Create curiosity or emotional impact
- Avoid clickbait while being compelling
- Match the tone: {{ tone }}

Target audience: {{ audience }}

Return ONLY a JSON array of objects:
[
    {"hook": "First hook text", "type": "curiosity|emotional|controversial"},
    {"hook": "Second hook text", "type": "..."},
    {"hook": "Third hook text", "type": "..."}
]
""",
            "script_writer": """You are a professional video script writer.
Write a complete script for a {{ duration }} minute video about: {{ topic }}

Original source material:
{{ source_content }}

Target audience: {{ audience }}
Tone: {{ tone }}
Channel style: {{ style }}

Structure:
1. Hook (0-10 seconds): Grab attention immediately
2. Intro (10-30 seconds): Set up the premise
3. Body (main content): {{ body_segments }} segments with clear transitions
4. CTA (10-15 seconds): Clear call to action
5. Outro (5-10 seconds): Wrap up

Requirements:
- Write for voiceover, not reading
- Include [VISUAL: description] cues for B-roll
- Keep sentences short and punchy
- Use conversational language
- Avoid: "Hey guys", "Welcome back", "Don't forget to like and subscribe"

Return JSON format:
{
    "title": "Video title",
    "hook": "Hook text",
    "intro": "Intro text with [VISUAL: ...] cues",
    "body": [
        {"segment": 1, "content": "...", "visual_notes": "..."},
        ...
    ],
    "cta": "Call to action",
    "outro": "Outro text",
    "estimated_duration_minutes": {{ duration }},
    "tags": ["tag1", "tag2", ...]
}
""",
            "seo_metadata": """Generate SEO-optimized metadata for a video.

Video Title: {{ title }}
Script Summary: {{ summary }}
Target Keywords: {{ keywords | join(', ') }}
Platform: {{ platform }}

Generate:
1. An optimized title (60 chars max, include keywords naturally)
2. A compelling description (150-200 words, keyword-rich but natural)
3. Tags (15 relevant tags)
4. Category suggestion
5. Thumbnail text ideas (3 options, max 5 words each)

Return JSON:
{
    "optimized_title": "...",
    "description": "...",
    "tags": ["..."],
    "category": "...",
    "thumbnail_text_options": ["...", "...", "..."]
}
""",
            "safety_check": """Check the following content for policy compliance:

Content Type: {{ content_type }}
Content:
{{ content }}

Check for:
1. Violence or gore
2. Adult/sexual content
3. Hate speech or harassment
4. Dangerous acts
5. Misinformation
6. Copyright concerns

Return JSON:
{
    "safe": true/false,
    "flags": ["violation_type"],
    "confidence": 0-1,
    "recommendations": ["..."]
}
""",
        }
        
        content = templates.get(name, "")
        if content:
            path.write_text(content)
            logger.info(f"Created default template: {name}")
    
    def render(
        self,
        template_name: str,
        **kwargs: Any,
    ) -> tuple[str, str]:
        """Render a template with variables.
        
        Args:
            template_name: Name of the template
            **kwargs: Template variables
            
        Returns:
            Tuple of (rendered_content, version_hash)
        """
        template = self.get_template(template_name)
        rendered = template.render(**kwargs)
        
        # Get template source for hashing
        with open(template.filename, "r") as f:
            source = f.read()
        version_hash = self._get_template_hash(source + str(kwargs))
        
        return rendered, version_hash


# Global prompt manager instance
_prompt_manager: PromptManager | None = None


def get_prompt_manager() -> PromptManager:
    """Get or create prompt manager."""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager
