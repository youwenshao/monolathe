"""Docker-based channel isolation manager."""

import asyncio
import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.shared.config import get_settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BrowserFingerprint:
    """Browser fingerprint configuration."""
    user_agent: str
    viewport: dict[str, int]
    timezone: str
    locale: str
    fonts: list[str]
    color_depth: int
    pixel_ratio: float


class FingerprintRotator:
    """Rotate browser fingerprints to avoid detection."""
    
    USER_AGENTS = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15",
        "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0_3 like Mac OS X) AppleWebKit/605.1.15",
    ]
    
    VIEWPORTS = [
        {"width": 390, "height": 844},
        {"width": 393, "height": 852},
        {"width": 412, "height": 915},
    ]
    
    TIMEZONES = ["America/New_York", "Europe/London", "Asia/Tokyo"]
    LOCALES = ["en-US", "en-GB", "en-CA"]
    
    def __init__(self, seed: str | None = None):
        self.rng = random.Random(seed)
    
    def generate_fingerprint(self, channel_id: str) -> BrowserFingerprint:
        """Generate unique fingerprint for channel."""
        channel_hash = int(hashlib.md5(channel_id.encode()).hexdigest(), 16)
        self.rng.seed(channel_hash)
        
        return BrowserFingerprint(
            user_agent=self.rng.choice(self.USER_AGENTS),
            viewport=self.rng.choice(self.VIEWPORTS),
            timezone=self.rng.choice(self.TIMEZONES),
            locale=self.rng.choice(self.LOCALES),
            fonts=["Arial", "Helvetica"],
            color_depth=24,
            pixel_ratio=2.0,
        )


class DockerChannelManager:
    """Manage isolated Docker containers per channel."""
    
    def __init__(self):
        self.settings = get_settings()
        self.fingerprint_rotator = FingerprintRotator()
        self._active_containers: dict[str, dict[str, Any]] = {}
    
    async def create_channel_container(
        self,
        channel_id: str,
        image: str = "mcr.microsoft.com/playwright:v1.49.0-jammy",
    ) -> dict[str, Any]:
        """Create isolated container for channel.
        
        Args:
            channel_id: Channel identifier
            image: Docker image to use
            
        Returns:
            Container info
        """
        fingerprint = self.fingerprint_rotator.generate_fingerprint(channel_id)
        
        config = {
            "Image": image,
            "name": f"sc-channel-{channel_id}",
            "Env": [
                f"CHANNEL_ID={channel_id}",
                f"USER_AGENT={fingerprint.user_agent}",
            ],
            "HostConfig": {
                "Memory": 2147483648,  # 2GB
                "CpuQuota": 100000,
            },
        }
        
        self._active_containers[channel_id] = {
            "config": config,
            "fingerprint": fingerprint.to_dict(),
            "created_at": datetime.utcnow().isoformat(),
            "status": "created",
        }
        
        logger.info(f"Container created for channel {channel_id}")
        return self._active_containers[channel_id]
    
    async def destroy_channel_container(self, channel_id: str) -> bool:
        """Destroy channel container."""
        if channel_id in self._active_containers:
            del self._active_containers[channel_id]
            logger.info(f"Container destroyed for channel {channel_id}")
            return True
        return False
    
    def get_container_status(self, channel_id: str) -> dict[str, Any] | None:
        """Get container status."""
        return self._active_containers.get(channel_id)
    
    def list_active_containers(self) -> list[dict[str, Any]]:
        """List all active containers."""
        return [
            {"channel_id": cid, "status": info["status"]}
            for cid, info in self._active_containers.items()
        ]


class AntiCorrelationEngine:
    """Prevent correlation between channels."""
    
    def __init__(self):
        self._channel_attributes: dict[str, dict[str, Any]] = {}
    
    def register_channel_attributes(
        self,
        channel_id: str,
        music_style: str,
        intro_style: str,
        posting_times: list[int],
        hashtag_strategy: str,
    ) -> None:
        """Register channel attributes for correlation checking."""
        self._channel_attributes[channel_id] = {
            "music_style": music_style,
            "intro_style": intro_style,
            "posting_times": posting_times,
            "hashtag_strategy": hashtag_strategy,
        }
    
    def check_correlation(
        self,
        channel_id: str,
        proposed_attributes: dict[str, Any],
    ) -> dict[str, Any]:
        """Check if proposed attributes correlate with existing channels.
        
        Returns:
            Correlation report with conflicts
        """
        conflicts = []
        
        for other_id, attrs in self._channel_attributes.items():
            if other_id == channel_id:
                continue
            
            # Check music style overlap
            if proposed_attributes.get("music_style") == attrs["music_style"]:
                conflicts.append({
                    "type": "music_style",
                    "channel": other_id,
                    "value": attrs["music_style"],
                })
            
            # Check intro style overlap
            if proposed_attributes.get("intro_style") == attrs["intro_style"]:
                conflicts.append({
                    "type": "intro_style",
                    "channel": other_id,
                    "value": attrs["intro_style"],
                })
            
            # Check posting time overlap
            time_overlap = set(proposed_attributes.get("posting_times", [])) & set(attrs["posting_times"])
            if len(time_overlap) > 2:
                conflicts.append({
                    "type": "posting_times",
                    "channel": other_id,
                    "overlap": list(time_overlap),
                })
        
        return {
            "has_conflicts": len(conflicts) > 0,
            "conflicts": conflicts,
            "recommendation": "Adjust attributes to reduce correlation" if conflicts else "No conflicts detected",
        }
