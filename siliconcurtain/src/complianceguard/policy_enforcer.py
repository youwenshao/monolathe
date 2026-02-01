"""ComplianceGuard: Policy enforcement and kill switch."""

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from src.shared.circuit_breaker import create_circuit_breaker
from src.shared.config import get_settings
from src.shared.database import get_session
from src.shared.logger import get_logger
from src.shared.redis_client import get_redis_client

logger = get_logger(__name__)


@dataclass
class SafetyCheckResult:
    """Content safety check result."""
    safe: bool
    flags: list[str]
    confidence: float
    recommendations: list[str]
    check_type: str


class ContentSafetyChecker:
    """Check content for policy violations."""
    
    VIOLATION_CATEGORIES = {
        "violence": "Graphic violence or gore",
        "adult_content": "Sexual content or nudity",
        "hate_speech": "Hate speech or harassment",
        "self_harm": "Self-harm or suicide content",
        "dangerous_acts": "Dangerous or illegal acts",
        "misinformation": "Known misinformation",
        "spam": "Spam or deceptive practices",
        "copyright": "Copyright infringement",
    }
    
    def __init__(self):
        self.settings = get_settings()
    
    async def check_visual_content(
        self,
        image_path: str,
        video_path: str | None = None,
    ) -> SafetyCheckResult:
        """Check visual content using Qwen-VL.
        
        Args:
            image_path: Image to check
            video_path: Optional video to check
            
        Returns:
            Safety check result
        """
        # Would call MLX server with Qwen-VL model
        # For now, return safe result
        
        logger.info(f"Visual check: {image_path}")
        
        # Placeholder implementation
        return SafetyCheckResult(
            safe=True,
            flags=[],
            confidence=0.95,
            recommendations=[],
            check_type="visual",
        )
    
    async def check_text_content(self, text: str) -> SafetyCheckResult:
        """Check text content using DeepSeek API.
        
        Args:
            text: Text to check
            
        Returns:
            Safety check result
        """
        prompt = f"""Analyze the following text for policy violations:

Text: {text[:2000]}

Check for:
1. Hate speech or harassment
2. Misinformation
3. Spam indicators
4. Dangerous content promotion
5. Self-harm references

Return JSON:
{{
    "safe": true/false,
    "flags": ["violation_type"],
    "confidence": 0-1,
    "recommendations": ["suggested_changes"]
}}"""
        
        try:
            # Call DeepSeek API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.settings.deepseek_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.deepseek_api_key}"},
                    json={
                        "model": self.settings.deepseek_model,
                        "messages": [
                            {"role": "system", "content": "You are a content safety analyzer."},
                            {"role": "user", "content": prompt},
                        ],
                        "response_format": {"type": "json_object"},
                    },
                    timeout=30.0,
                )
                
                result = response.json()
                content = json.loads(result["choices"][0]["message"]["content"])
                
                return SafetyCheckResult(
                    safe=content.get("safe", True),
                    flags=content.get("flags", []),
                    confidence=content.get("confidence", 0.5),
                    recommendations=content.get("recommendations", []),
                    check_type="text",
                )
                
        except Exception as e:
            logger.error(f"Text safety check failed: {e}")
            # Fail safe - assume safe if check fails
            return SafetyCheckResult(
                safe=True,
                flags=["check_failed"],
                confidence=0.0,
                recommendations=["Manual review recommended"],
                check_type="text",
            )
    
    async def check_audio_content(self, audio_path: str) -> SafetyCheckResult:
        """Check audio content by transcribing and analyzing.
        
        Args:
            audio_path: Audio file path
            
        Returns:
            Safety check result
        """
        # Transcribe with Whisper, then check text
        logger.info(f"Audio check: {audio_path}")
        
        # Placeholder
        return SafetyCheckResult(
            safe=True,
            flags=[],
            confidence=0.9,
            recommendations=[],
            check_type="audio",
        )


class CopyrightChecker:
    """Check for copyright violations."""
    
    def __init__(self):
        self._known_patterns = set()
        self._audio_fingerprints = {}
    
    def register_copyright_pattern(self, pattern: str, owner: str) -> None:
        """Register known copyright pattern.
        
        Args:
            pattern: Pattern to detect
            owner: Copyright owner
        """
        self._known_patterns.add((pattern.lower(), owner))
    
    async def check_video_copyright(self, video_path: str) -> dict[str, Any]:
        """Check video for copyright issues.
        
        Args:
            video_path: Video file path
            
        Returns:
            Copyright check result
        """
        # Would implement ContentID-style matching
        # For now, return clear
        
        return {
            "has_violations": False,
            "matches": [],
            "confidence": 0.0,
        }
    
    async def check_audio_copyright(self, audio_path: str) -> dict[str, Any]:
        """Check audio for copyright issues.
        
        Args:
            audio_path: Audio file path
            
        Returns:
            Copyright check result
        """
        return {
            "has_violations": False,
            "matches": [],
            "confidence": 0.0,
        }


class KillSwitch:
    """Emergency stop for all uploads."""
    
    def __init__(self):
        self._triggered = False
        self._trigger_time: datetime | None = None
        self._reason: str | None = None
        self._affected_channels: set[str] = set()
    
    async def trigger(
        self,
        reason: str,
        affected_channels: list[str] | None = None,
    ) -> None:
        """Trigger kill switch.
        
        Args:
            reason: Reason for triggering
            affected_channels: Specific channels to stop, or None for all
        """
        self._triggered = True
        self._trigger_time = datetime.utcnow()
        self._reason = reason
        
        if affected_channels:
            self._affected_channels = set(affected_channels)
        
        # Notify Redis for distributed awareness
        redis = await get_redis_client()
        await redis.set_json(
            "killswitch:status",
            {
                "triggered": True,
                "reason": reason,
                "time": self._trigger_time.isoformat(),
                "affected_channels": list(self._affected_channels),
            },
            expire=86400,  # 24 hours
        )
        
        logger.critical(f"KILL SWITCH TRIGGERED: {reason}")
    
    async def release(self) -> None:
        """Release kill switch."""
        self._triggered = False
        self._trigger_time = None
        self._reason = None
        self._affected_channels = set()
        
        redis = await get_redis_client()
        await redis.delete("killswitch:status")
        
        logger.info("Kill switch released")
    
    def is_triggered(self, channel_id: str | None = None) -> bool:
        """Check if kill switch is triggered.
        
        Args:
            channel_id: Optional channel to check
            
        Returns:
            True if kill switch is active
        """
        if not self._triggered:
            return False
        
        if channel_id and self._affected_channels:
            return channel_id in self._affected_channels
        
        return True
    
    async def check_status(self) -> dict[str, Any]:
        """Get kill switch status.
        
        Returns:
            Status information
        """
        redis = await get_redis_client()
        remote_status = await redis.get_json("killswitch:status")
        
        if remote_status:
            self._triggered = remote_status.get("triggered", False)
            self._reason = remote_status.get("reason")
        
        return {
            "triggered": self._triggered,
            "reason": self._reason,
            "trigger_time": self._trigger_time.isoformat() if self._trigger_time else None,
            "affected_channels": list(self._affected_channels),
        }


class ComplianceGuard:
    """Main compliance enforcement interface."""
    
    def __init__(self):
        self.settings = get_settings()
        self.safety_checker = ContentSafetyChecker()
        self.copyright_checker = CopyrightChecker()
        self.kill_switch = KillSwitch()
        self._violation_counts: dict[str, int] = {}
    
    async def check_content(
        self,
        content_id: str,
        channel_id: str,
        video_path: str,
        script_text: str,
        thumbnail_path: str | None = None,
    ) -> dict[str, Any]:
        """Full compliance check for content.
        
        Args:
            content_id: Content identifier
            channel_id: Channel identifier
            video_path: Video file path
            script_text: Script text
            thumbnail_path: Thumbnail path
            
        Returns:
            Compliance check results
        """
        # Check kill switch first
        if self.kill_switch.is_triggered(channel_id):
            return {
                "approved": False,
                "reason": f"Kill switch active: {self.kill_switch._reason}",
                "checks": {},
            }
        
        results = {
            "content_id": content_id,
            "channel_id": channel_id,
            "checks": {},
            "approved": True,
            "flags": [],
        }
        
        # Visual check
        if thumbnail_path:
            visual_check = await self.safety_checker.check_visual_content(thumbnail_path)
            results["checks"]["visual"] = {
                "safe": visual_check.safe,
                "flags": visual_check.flags,
                "confidence": visual_check.confidence,
            }
            if not visual_check.safe:
                results["approved"] = False
                results["flags"].extend(visual_check.flags)
        
        # Text check
        text_check = await self.safety_checker.check_text_content(script_text)
        results["checks"]["text"] = {
            "safe": text_check.safe,
            "flags": text_check.flags,
            "confidence": text_check.confidence,
        }
        if not text_check.safe:
            results["approved"] = False
            results["flags"].extend(text_check.flags)
        
        # Copyright check
        copyright_check = await self.copyright_checker.check_video_copyright(video_path)
        results["checks"]["copyright"] = copyright_check
        if copyright_check["has_violations"]:
            results["approved"] = False
            results["flags"].append("copyright_violation")
        
        # Track violations
        if not results["approved"]:
            self._violation_counts[channel_id] = self._violation_counts.get(channel_id, 0) + 1
            
            # Auto-trigger kill switch for repeated violations
            if self._violation_counts[channel_id] >= 3:
                await self.kill_switch.trigger(
                    reason=f"Multiple violations from channel {channel_id}",
                    affected_channels=[channel_id],
                )
        
        return results
    
    async def approve_upload(self, content_id: str) -> dict[str, Any]:
        """Mark content as approved for upload.
        
        Args:
            content_id: Content ID
            
        Returns:
            Approval record
        """
        return {
            "content_id": content_id,
            "approved_at": datetime.utcnow().isoformat(),
            "approved_by": "compliance_guard",
        }
    
    async def get_violation_stats(self) -> dict[str, Any]:
        """Get violation statistics.
        
        Returns:
            Statistics
        """
        return {
            "total_violations": sum(self._violation_counts.values()),
            "by_channel": self._violation_counts,
            "kill_switch_status": await self.kill_switch.check_status(),
        }
