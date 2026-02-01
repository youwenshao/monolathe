"""Trend analysis and virality scoring using DeepSeek API."""

import json
from typing import Any

import httpx

from src.shared.circuit_breaker import CircuitBreakerError, create_circuit_breaker
from src.shared.config import get_settings
from src.shared.logger import get_logger
from src.shared.models import TrendSource, ViralityScore

logger = get_logger(__name__)

# System prompt for virality scoring
VIRALITY_SCORING_PROMPT = """You are a viral content expert. Analyze the following content and predict its virality potential.

Rate the content on a scale of 0-100 based on:
- Emotional impact (curiosity, controversy, relatability)
- Shareability factor
- Timeliness and relevance
- Audience appeal breadth
- Hook strength in the first 3 seconds

Provide your response in this exact JSON format:
{
    "score": <number 0-100>,
    "reasoning": "<brief explanation>",
    "target_demographic": ["<audience segment 1>", "<audience segment 2>"],
    "recommended_format": "<short_form|long_form|series>"
}

Be objective and analytical."""


class DeepSeekAnalyzer:
    """DeepSeek API client for trend analysis."""
    
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None
        
        # Create circuit breaker for DeepSeek API
        self._circuit_breaker = create_circuit_breaker(
            name="deepseek_api",
            failure_threshold=3,
            recovery_timeout=60.0,
            expected_exception=(httpx.HTTPError, httpx.TimeoutException),
        )
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.settings.deepseek_base_url,
                timeout=self.settings.deepseek_timeout,
                headers={
                    "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def _call_api(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Make API call to DeepSeek with circuit breaker."""
        client = await self._get_client()
        
        payload = {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
        }
        
        try:
            # Use circuit breaker
            async def _make_request() -> httpx.Response:
                return await client.post("/chat/completions", json=payload)
            
            response = await self._circuit_breaker.call(_make_request)
            response.raise_for_status()
            
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
            
        except CircuitBreakerError:
            logger.warning("DeepSeek circuit breaker is OPEN, using fallback")
            raise
        except httpx.TimeoutException as e:
            logger.error(f"DeepSeek API timeout: {e}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"DeepSeek API error: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse DeepSeek response: {e}")
            raise
    
    async def calculate_virality(
        self,
        title: str,
        source: TrendSource,
        raw_data: dict[str, Any],
    ) -> ViralityScore:
        """Calculate virality score for content.
        
        Args:
            title: Content title/headline
            source: Source platform
            raw_data: Raw scraped data
            
        Returns:
            ViralityScore with score and analysis
        """
        # Build context from raw data
        context = self._build_context(source, raw_data)
        
        messages = [
            {"role": "system", "content": VIRALITY_SCORING_PROMPT},
            {
                "role": "user",
                "content": f"Title: {title}\nSource: {source.value}\nContext: {context}",
            },
        ]
        
        try:
            result = await self._call_api(messages)
            
            return ViralityScore(
                score=result.get("score", 50),
                reasoning=result.get("reasoning", "No analysis provided"),
                target_demographic=result.get("target_demographic", []),
                recommended_format=result.get("recommended_format", "short_form"),
            )
            
        except CircuitBreakerError:
            # Fallback: calculate basic score from engagement metrics
            return self._fallback_scoring(source, raw_data)
        except Exception as e:
            logger.error(f"Virality calculation failed: {e}")
            return ViralityScore(
                score=50,
                reasoning=f"Error during analysis: {e}",
                target_demographic=["general"],
            )
    
    def _build_context(self, source: TrendSource, raw_data: dict[str, Any]) -> str:
        """Build analysis context from raw data."""
        context_parts = []
        
        if source == TrendSource.REDDIT:
            if "score" in raw_data:
                context_parts.append(f"Upvotes: {raw_data['score']}")
            if "num_comments" in raw_data:
                context_parts.append(f"Comments: {raw_data['num_comments']}")
            if "upvote_ratio" in raw_data:
                context_parts.append(f"Upvote ratio: {raw_data['upvote_ratio']}")
        
        elif source == TrendSource.YOUTUBE:
            if "view_count" in raw_data:
                context_parts.append(f"Views: {raw_data['view_count']}")
            if "duration" in raw_data:
                context_parts.append(f"Duration: {raw_data['duration']}s")
        
        return "; ".join(context_parts) if context_parts else "No additional context"
    
    def _fallback_scoring(
        self,
        source: TrendSource,
        raw_data: dict[str, Any],
    ) -> ViralityScore:
        """Fallback scoring when API is unavailable."""
        score = 50  # Default neutral score
        
        if source == TrendSource.REDDIT:
            # Score based on engagement ratio
            upvotes = raw_data.get("score", 0)
            comments = raw_data.get("num_comments", 0)
            ratio = raw_data.get("upvote_ratio", 0.5)
            
            # Normalize to 0-100
            engagement = min(100, (upvotes + comments * 10) / 1000 * 100)
            score = int(engagement * ratio)
        
        elif source == TrendSource.YOUTUBE:
            views = raw_data.get("view_count", 0)
            score = min(100, views / 100000 * 100)  # 100k views = 100 score
        
        return ViralityScore(
            score=score,
            reasoning="Fallback scoring (API unavailable)",
            target_demographic=["general"],
            recommended_format="short_form",
        )


class TrendAnalyzer:
    """High-level trend analysis coordinator."""
    
    def __init__(self) -> None:
        self.deepseek = DeepSeekAnalyzer()
    
    async def close(self) -> None:
        """Cleanup resources."""
        await self.deepseek.close()
    
    async def analyze_trends(
        self,
        trends_data: dict[TrendSource, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Analyze and score multiple trends.
        
        Args:
            trends_data: Dictionary of source -> raw trends
            
        Returns:
            List of analyzed trends with virality scores
        """
        analyzed = []
        
        for source, trends in trends_data.items():
            for trend in trends:
                try:
                    title = trend.get("title", "")
                    if not title:
                        continue
                    
                    score = await self.deepseek.calculate_virality(
                        title=title,
                        source=source,
                        raw_data=trend,
                    )
                    
                    analyzed.append({
                        "source": source.value,
                        "title": title,
                        "raw_data": trend,
                        "virality_score": score.score,
                        "virality_analysis": score.reasoning,
                        "target_demographic": score.target_demographic,
                        "recommended_format": score.recommended_format,
                    })
                    
                except Exception as e:
                    logger.error(f"Failed to analyze trend: {e}")
                    continue
        
        # Sort by virality score descending
        analyzed.sort(key=lambda x: x["virality_score"], reverse=True)
        
        logger.info(f"Analyzed {len(analyzed)} trends")
        return analyzed
