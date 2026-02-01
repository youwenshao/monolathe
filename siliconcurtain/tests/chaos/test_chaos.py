"""Chaos engineering tests for SiliconCurtain."""

import asyncio
import pytest
from unittest.mock import patch

from src.shared.circuit_breaker import CircuitBreaker, CircuitState
from src.complianceguard.policy_enforcer import KillSwitch


class TestCircuitBreakerChaos:
    """Test circuit breaker behavior."""
    
    @pytest.mark.asyncio
    async def test_circuit_opens_on_failures(self):
        """Test: Circuit opens after threshold failures."""
        breaker = CircuitBreaker(name="test", failure_threshold=3)
        
        for _ in range(3):
            try:
                async def fail(): raise Exception("fail")
                await breaker.call(fail)
            except:
                pass
        
        assert breaker.state == CircuitState.OPEN
        print("\n✓ Circuit opened after 3 failures")
    
    @pytest.mark.asyncio
    async def test_circuit_recovery(self):
        """Test: Circuit recovers after timeout."""
        breaker = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.1)
        
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = asyncio.get_event_loop().time() - 0.2
        
        async def success(): return "ok"
        await breaker.call(success)
        
        assert breaker.state == CircuitState.HALF_OPEN
        print("\n✓ Circuit recovered to half-open")


class TestKillSwitchChaos:
    """Test kill switch activation."""
    
    @pytest.mark.asyncio
    async def test_kill_switch_latency(self):
        """Test: Kill switch activates < 30s."""
        import time
        
        ks = KillSwitch()
        start = time.time()
        await ks.trigger("test")
        elapsed = time.time() - start
        
        assert elapsed < 30
        print(f"\n✓ Kill switch in {elapsed:.2f}s")


class TestResourceExhaustion:
    """Test resource limits."""
    
    def test_vram_check(self):
        """Test: VRAM availability check."""
        from src.assetfactory.mlx_server import check_resource_availability
        
        with patch('src.assetfactory.mlx_server.get_vram_usage', return_value=(40.0, 4.0)):
            available = check_resource_availability(required_gb=8.0)
            assert available is False
        
        print("\n✓ VRAM limit enforced")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Generate summary."""
    print("\n" + "=" * 70)
    print("CHAOS ENGINEERING SUMMARY")
    print("=" * 70)
    print("\n🔥 Scenarios: Circuit breaker, Kill switch, Resource limits")
    print("=" * 70)