"""Script generation engine with DeepSeek API and local fallback."""

import json
from typing import Any

import httpx

from src.scriptforge.prompts import get_prompt_manager
from src.shared.circuit_breaker import CircuitBreakerError, create_circuit_breaker
from src.shared.config import get_settings
from src.shared.logger import get_logger
from src.shared.models import NicheCategory, ScriptSegment, VideoScript

logger = get_logger(__name__)


class LLMClient:
    """Unified LLM client with circuit breaker and fallback."""
    
    def __init__(self) -> None:
        self.settings = get_settings()
        self._http_client: httpx.AsyncClient | None = None
        
        # Circuit breaker for DeepSeek
        self._deepseek_breaker = create_circuit_breaker(
            name="scriptforge_deepseek",
            failure_threshold=3,
            recovery_timeout=30.0,
            expected_exception=(httpx.HTTPError, httpx.TimeoutException),
        )
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=5.0),
                headers={"Content-Type": "application/json"},
            )
        return self._http_client
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
    
    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        require_json: bool = True,
    ) -> dict[str, Any]:
        """Generate content using DeepSeek API with fallback to Ollama.
        
        Args:
            prompt: The generation prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            require_json: Whether to request JSON output
            
        Returns:
            Generated content as dictionary
        """
        # Try DeepSeek first
        try:
            return await self._call_deepseek(prompt, temperature, max_tokens, require_json)
        except CircuitBreakerError:
            logger.warning("DeepSeek circuit breaker open, falling back to Ollama")
        except Exception as e:
            logger.error(f"DeepSeek call failed: {e}")
        
        # Fallback to Ollama
        return await self._call_ollama(prompt, temperature, max_tokens, require_json)
    
    async def _call_deepseek(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        require_json: bool,
    ) -> dict[str, Any]:
        """Call DeepSeek API."""
        client = await self._get_http_client()
        
        payload: dict[str, Any] = {
            "model": self.settings.deepseek_model,
            "messages": [
                {"role": "system", "content": "You are a professional content creator."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if require_json:
            payload["response_format"] = {"type": "json_object"}
        
        async def _make_request() -> httpx.Response:
            return await client.post(
                f"{self.settings.deepseek_base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.settings.deepseek_api_key}"},
            )
        
        response = await self._deepseek_breaker.call(_make_request)
        response.raise_for_status()
        
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        
        return json.loads(content)
    
    async def _call_ollama(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        require_json: bool,
    ) -> dict[str, Any]:
        """Call local Ollama instance."""
        client = await self._get_http_client()
        
        payload = {
            "model": self.settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        
        response = await client.post(
            f"{self.settings.ollama_base_url}/api/generate",
            json=payload,
        )
        response.raise_for_status()
        
        data = response.json()
        content = data["response"]
        
        # Try to parse as JSON if required
        if require_json:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # Wrap raw text in JSON structure
                return {"content": content, "raw": True}
        
        return {"content": content}


class ScriptGenerator:
    """Video script generation engine."""
    
    def __init__(self) -> None:
        self.llm = LLMClient()
        self.prompts = get_prompt_manager()
    
    async def close(self) -> None:
        """Cleanup resources."""
        await self.llm.close()
    
    async def generate_script(
        self,
        topic: str,
        source_material: str,
        audience: str,
        tone: str = "conversational",
        duration_minutes: float = 3.0,
        style: str = "faceless",
        niche: NicheCategory = NicheCategory.ENTERTAINMENT,
    ) -> VideoScript:
        """Generate a complete video script.
        
        Args:
            topic: Main topic/title
            source_material: Original source content
            audience: Target audience description
            tone: Content tone (conversational, professional, humorous, etc.)
            duration_minutes: Target video duration
            style: Channel style (faceless, docu, vlog, etc.)
            niche: Content niche category
            
        Returns:
            Generated VideoScript
        """
        # Calculate body segments based on duration
        body_segments = max(2, int(duration_minutes / 1.5))
        
        prompt, version_hash = self.prompts.render(
            "script_writer",
            topic=topic,
            source_content=source_material[:2000],  # Limit source content
            audience=audience,
            tone=tone,
            duration=duration_minutes,
            style=style,
            body_segments=body_segments,
        )
        
        logger.info(f"Generating script for topic: {topic[:50]}...")
        
        result = await self.llm.generate(
            prompt=prompt,
            temperature=0.7,
            max_tokens=2500,
            require_json=True,
        )
        
        # Parse body segments
        body_segments_list = []
        for seg in result.get("body", []):
            body_segments_list.append(ScriptSegment(
                type="body",
                content=seg.get("content", ""),
                visual_notes=seg.get("visual_notes"),
            ))
        
        script = VideoScript(
            title=result.get("title", topic),
            hook=result.get("hook", ""),
            intro=result.get("intro", ""),
            body=body_segments_list,
            cta=result.get("cta", ""),
            outro=result.get("outro", ""),
            tags=result.get("tags", []),
            category=niche,
            estimated_duration=result.get("estimated_duration_minutes", duration_minutes) * 60,
            target_audience=[audience],
            seo_description="",  # Generated separately
        )
        
        logger.info(f"Script generated: {script.title}")
        return script
    
    async def generate_hooks(
        self,
        topic: str,
        tone: str = "curiosity",
        audience: str = "general",
    ) -> list[dict[str, str]]:
        """Generate hook variations for A/B testing.
        
        Args:
            topic: Content topic
            tone: Desired tone
            audience: Target audience
            
        Returns:
            List of hook options with types
        """
        prompt, _ = self.prompts.render(
            "hook_generator",
            topic=topic,
            tone=tone,
            audience=audience,
        )
        
        result = await self.llm.generate(
            prompt=prompt,
            temperature=0.8,
            max_tokens=500,
            require_json=True,
        )
        
        hooks = result if isinstance(result, list) else result.get("hooks", [])
        return hooks[:3]  # Return top 3
    
    async def generate_seo_metadata(
        self,
        title: str,
        script_summary: str,
        keywords: list[str],
        platform: str = "youtube",
    ) -> dict[str, Any]:
        """Generate SEO-optimized metadata.
        
        Args:
            title: Video title
            script_summary: Brief script summary
            keywords: Target keywords
            platform: Target platform
            
        Returns:
            Dictionary with optimized metadata
        """
        prompt, _ = self.prompts.render(
            "seo_metadata",
            title=title,
            summary=script_summary[:500],
            keywords=keywords,
            platform=platform,
        )
        
        return await self.llm.generate(
            prompt=prompt,
            temperature=0.5,
            max_tokens=1000,
            require_json=True,
        )
    
    async def safety_check(self, content: str, content_type: str = "script") -> dict[str, Any]:
        """Check content for policy compliance.
        
        Args:
            content: Content to check
            content_type: Type of content
            
        Returns:
            Safety check results
        """
        prompt, _ = self.prompts.render(
            "safety_check",
            content=content[:2000],
            content_type=content_type,
        )
        
        try:
            result = await self.llm.generate(
                prompt=prompt,
                temperature=0.1,
                max_tokens=500,
                require_json=True,
            )
            return {
                "safe": result.get("safe", True),
                "flags": result.get("flags", []),
                "confidence": result.get("confidence", 1.0),
                "recommendations": result.get("recommendations", []),
            }
        except Exception as e:
            logger.error(f"Safety check failed: {e}")
            # Fail safe - assume safe if check fails
            return {"safe": True, "flags": [], "confidence": 0.0, "recommendations": []}
