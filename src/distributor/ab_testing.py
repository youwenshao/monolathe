"""A/B Testing Framework for Instagram Reels optimization."""

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.shared.config import get_settings
from src.shared.database import get_session
from src.shared.logger import get_logger
from src.shared.models_reels import ReelsVideoScript

logger = get_logger(__name__)


@dataclass
class Variant:
    """A/B test variant."""
    id: str
    name: str
    content_id: str
    changes: dict[str, Any]
    traffic_allocation: float  # 0.0 - 1.0
    metrics: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "content_id": self.content_id,
            "changes": self.changes,
            "traffic_allocation": self.traffic_allocation,
            "metrics": self.metrics,
        }


@dataclass
class ABTest:
    """A/B test configuration."""
    id: str
    name: str
    content_id: str
    variants: list[Variant]
    start_time: datetime
    end_time: datetime | None
    success_metric: str
    minimum_sample_size: int
    confidence_level: float  # e.g., 0.95 for 95%
    status: str = "running"  # running, completed, cancelled
    winner_variant_id: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "content_id": self.content_id,
            "variants": [v.to_dict() for v in self.variants],
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "success_metric": self.success_metric,
            "minimum_sample_size": self.minimum_sample_size,
            "confidence_level": self.confidence_level,
            "status": self.status,
            "winner_variant_id": self.winner_variant_id,
        }


class ABTestingFramework:
    """Manage A/B tests for Reels optimization."""
    
    # Testable elements with variation strategies
    TESTABLE_ELEMENTS = {
        "hook_text": {
            "description": "First 3 seconds hook",
            "variation_strategy": "generate_alternatives",
        },
        "cover_text": {
            "description": "Cover image text overlay",
            "variation_strategy": "text_variations",
        },
        "caption_cta": {
            "description": "Call-to-action in caption",
            "variation_strategy": "cta_variations",
        },
        "hashtag_set": {
            "description": "Hashtag selection",
            "variation_strategy": "hashtag_alternatives",
        },
        "posting_time": {
            "description": "Time of day to post",
            "variation_strategy": "time_slots",
        },
        "audio_selection": {
            "description": "Background audio",
            "variation_strategy": "audio_alternatives",
        },
    }
    
    def __init__(self):
        self.settings = get_settings()
        self._active_tests: dict[str, ABTest] = {}
    
    def create_test(
        self,
        name: str,
        content_id: str,
        base_script: ReelsVideoScript,
        element: str,
        num_variants: int = 2,
        duration_hours: int = 24,
        success_metric: str = "engagement_rate",
    ) -> ABTest:
        """Create A/B test for content element.
        
        Args:
            name: Test name
            content_id: Base content ID
            base_script: Base video script
            element: Element to test (hook_text, cover_text, etc.)
            num_variants: Number of variants (2-4)
            duration_hours: Test duration
            success_metric: Metric to optimize
            
        Returns:
            Created test
        """
        if element not in self.TESTABLE_ELEMENTS:
            raise ValueError(f"Invalid element: {element}")
        
        test_id = f"ab_{content_id}_{element}_{int(datetime.utcnow().timestamp())}"
        
        # Generate variants
        variants = self._generate_variants(
            content_id=content_id,
            base_script=base_script,
            element=element,
            num_variants=num_variants,
        )
        
        test = ABTest(
            id=test_id,
            name=name,
            content_id=content_id,
            variants=variants,
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(hours=duration_hours),
            success_metric=success_metric,
            minimum_sample_size=1000,
            confidence_level=0.95,
        )
        
        self._active_tests[test_id] = test
        
        logger.info(f"A/B test created: {test_id} for {element}")
        return test
    
    def _generate_variants(
        self,
        content_id: str,
        base_script: ReelsVideoScript,
        element: str,
        num_variants: int,
    ) -> list[Variant]:
        """Generate test variants.
        
        Args:
            content_id: Base content ID
            base_script: Base script
            element: Element to vary
            num_variants: Number of variants
            
        Returns:
            List of variants
        """
        variants = []
        allocation = 1.0 / num_variants
        
        for i in range(num_variants):
            variant_id = f"v{i}_{content_id}"
            
            changes = self._create_element_variation(
                base_script=base_script,
                element=element,
                variant_index=i,
            )
            
            variant = Variant(
                id=variant_id,
                name=f"Variant {chr(65 + i)}",  # A, B, C...
                content_id=f"{content_id}_v{i}",
                changes=changes,
                traffic_allocation=allocation,
            )
            variants.append(variant)
        
        return variants
    
    def _create_element_variation(
        self,
        base_script: ReelsVideoScript,
        element: str,
        variant_index: int,
    ) -> dict[str, Any]:
        """Create variation for specific element.
        
        Args:
            base_script: Base script
            element: Element to vary
            variant_index: Variant index
            
        Returns:
            Changes dictionary
        """
        if element == "hook_text":
            hooks = [
                base_script.hook,
                f"Wait for it... {base_script.hook}",
                f"POV: {base_script.hook}",
                f"This changes everything: {base_script.hook}",
            ]
            return {"hook": hooks[variant_index % len(hooks)]}
        
        elif element == "cover_text":
            texts = [
                base_script.cover_text,
                f"Part 1: {base_script.cover_text[:30]}",
                f"The truth about {base_script.cover_text[:20]}",
            ]
            return {"cover_text": texts[variant_index % len(texts)]}
        
        elif element == "caption_cta":
            ctas = [
                "Follow for more",
                "Save this for later",
                "Share with someone who needs this",
                "Comment your thoughts",
            ]
            return {"cta": ctas[variant_index % len(ctas)]}
        
        elif element == "posting_time":
            # 4 time slots throughout day
            hours = [9, 13, 17, 20]
            return {"posting_hour": hours[variant_index % len(hours)]}
        
        return {}
    
    def assign_variant(self, test_id: str, user_id: str | None = None) -> Variant:
        """Assign variant to user/session.
        
        Args:
            test_id: Test ID
            user_id: Optional user identifier
            
        Returns:
            Assigned variant
        """
        test = self._active_tests.get(test_id)
        if not test:
            raise ValueError(f"Test {test_id} not found")
        
        # Deterministic assignment based on user_id or random
        if user_id:
            hash_val = int(hashlib.md5(f"{test_id}:{user_id}".encode()).hexdigest(), 16)
            rand_val = (hash_val % 1000) / 1000
        else:
            rand_val = random.random()
        
        # Select variant based on allocation
        cumulative = 0.0
        for variant in test.variants:
            cumulative += variant.traffic_allocation
            if rand_val <= cumulative:
                return variant
        
        # Fallback to last variant
        return test.variants[-1]
    
    async def record_metrics(
        self,
        test_id: str,
        variant_id: str,
        metrics: dict[str, Any],
    ) -> None:
        """Record metrics for variant.
        
        Args:
            test_id: Test ID
            variant_id: Variant ID
            metrics: Performance metrics
        """
        test = self._active_tests.get(test_id)
        if not test:
            return
        
        for variant in test.variants:
            if variant.id == variant_id:
                variant.metrics.update(metrics)
                break
        
        logger.debug(f"Metrics recorded for {test_id}/{variant_id}")
    
    def analyze_results(self, test_id: str) -> dict[str, Any]:
        """Analyze test results and determine winner.
        
        Args:
            test_id: Test ID
            
        Returns:
            Analysis results
        """
        test = self._active_tests.get(test_id)
        if not test:
            return {"error": "Test not found"}
        
        # Calculate sample sizes
        for variant in test.variants:
            variant.metrics["sample_size"] = variant.metrics.get("views", 0)
        
        # Check minimum sample
        min_sample = min(v.metrics.get("sample_size", 0) for v in test.variants)
        if min_sample < test.minimum_sample_size:
            return {
                "status": "insufficient_data",
                "minimum_required": test.minimum_sample_size,
                "current_minimum": min_sample,
                "progress": min_sample / test.minimum_sample_size,
            }
        
        # Get success metric values
        scores = []
        for variant in test.variants:
            score = variant.metrics.get(test.success_metric, 0)
            sample = variant.metrics.get("sample_size", 1)
            scores.append({
                "variant_id": variant.id,
                "score": score,
                "sample_size": sample,
            })
        
        # Find winner
        scores.sort(key=lambda x: x["score"], reverse=True)
        winner = scores[0]
        runner_up = scores[1] if len(scores) > 1 else None
        
        # Calculate statistical significance (simplified)
        if runner_up:
            diff = winner["score"] - runner_up["score"]
            relative_lift = diff / runner_up["score"] if runner_up["score"] > 0 else 0
            is_significant = relative_lift > 0.05  # 5% lift threshold
        else:
            relative_lift = 0
            is_significant = False
        
        return {
            "test_id": test_id,
            "status": "completed" if is_significant else "inconclusive",
            "winner": winner,
            "all_scores": scores,
            "relative_lift": relative_lift,
            "is_statistically_significant": is_significant,
            "confidence_level": test.confidence_level,
            "recommendation": f"Use variant {winner['variant_id']}" if is_significant else "Continue testing",
        }
    
    def get_test_status(self, test_id: str) -> dict[str, Any]:
        """Get current test status.
        
        Args:
            test_id: Test ID
            
        Returns:
            Test status
        """
        test = self._active_tests.get(test_id)
        if not test:
            return {"error": "Test not found"}
        
        now = datetime.utcnow()
        is_expired = test.end_time and now > test.end_time
        
        return {
            "test_id": test_id,
            "name": test.name,
            "status": test.status,
            "is_expired": is_expired,
            "time_remaining": (test.end_time - now).total_seconds() if test.end_time and not is_expired else 0,
            "variant_metrics": [v.to_dict() for v in test.variants],
        }
    
    def end_test(self, test_id: str, declare_winner: bool = True) -> dict[str, Any]:
        """End test and optionally declare winner.
        
        Args:
            test_id: Test ID
            declare_winner: Whether to analyze and declare winner
            
        Returns:
            Final results
        """
        test = self._active_tests.get(test_id)
        if not test:
            return {"error": "Test not found"}
        
        test.status = "completed"
        test.end_time = datetime.utcnow()
        
        if declare_winner:
            analysis = self.analyze_results(test_id)
            if analysis.get("status") == "completed":
                test.winner_variant_id = analysis["winner"]["variant_id"]
            return analysis
        
        return {"status": "ended_without_winner"}
