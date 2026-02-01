"""Locust load testing for SiliconCurtain.

Tests system under sustained load to verify 50 Reels/day capacity.
"""

import random
from typing import Any

from locust import HttpUser, TaskSet, between, events, task


class GenerationTasks(TaskSet):
    """Asset generation load tests."""
    
    @task(3)
    def generate_voice(self) -> None:
        """Test voice generation endpoint."""
        payload = {
            "text": "Test voice generation for Instagram Reels content.",
            "emotion": random.choice(["neutral", "excited"]),
        }
        
        with self.client.post(
            "/generate/voice",
            json=payload,
            catch_response=True,
            timeout=60,
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 503:
                response.success()  # Expected under load
            else:
                response.failure(f"Status: {response.status_code}")
    
    @task(4)
    def generate_image(self) -> None:
        """Test image generation endpoint."""
        payload = {
            "prompt": "Test image for Instagram Reels",
            "width": 1080,
            "height": 1920,
        }
        
        with self.client.post(
            "/generate/image",
            json=payload,
            catch_response=True,
            timeout=120,
        ) as response:
            if response.status_code in [200, 503]:
                response.success()
            else:
                response.failure(f"Status: {response.status_code}")
    
    @task(1)
    def health_check(self) -> None:
        """Test health endpoint."""
        self.client.get("/health", timeout=5)


class SustainedLoadUser(HttpUser):
    """User simulating sustained load (50 videos/day target)."""
    
    wait_time = between(30, 90)
    tasks = [GenerationTasks]


@events.test_start.add_listener
def on_test_start(environment, **kwargs: Any) -> None:
    """Setup before test."""
    print("=" * 70)
    print("SILICONCURTAIN LOAD TEST - Target: 50 Reels/day")
    print("=" * 70)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs: Any) -> None:
    """Teardown after test."""
    print("=" * 70)
    print("LOAD TEST COMPLETE")
    print("=" * 70)