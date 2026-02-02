"""Tests for circuit breaker implementation."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.shared.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
)


class TestCircuitBreaker:
    """Test cases for CircuitBreaker class."""
    
    @pytest.fixture
    def breaker(self):
        """Create a test circuit breaker."""
        return CircuitBreaker(
            name="test_breaker",
            failure_threshold=3,
            recovery_timeout=1.0,
        )
    
    @pytest.mark.asyncio
    async def test_initial_state_closed(self, breaker):
        """Test initial state is CLOSED."""
        assert breaker.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_successful_call(self, breaker):
        """Test successful function call."""
        async def success_func():
            return "success"
        
        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_failure_counting(self, breaker):
        """Test that failures are counted."""
        async def fail_func():
            raise ValueError("Test error")
        
        # First two failures should stay CLOSED
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(fail_func)
        
        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 2
    
    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self, breaker):
        """Test circuit opens after failure threshold."""
        async def fail_func():
            raise ValueError("Test error")
        
        # Trigger failures to open circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail_func)
        
        assert breaker.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_circuit_opens_rejects_calls(self, breaker):
        """Test that open circuit rejects calls."""
        # Manually open the circuit
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = asyncio.get_event_loop().time()
        
        async def any_func():
            return "should not run"
        
        with pytest.raises(CircuitBreakerError):
            await breaker.call(any_func)
    
    @pytest.mark.asyncio
    async def test_half_open_transitions(self, breaker):
        """Test transition to HALF_OPEN after timeout."""
        # Open the circuit
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = asyncio.get_event_loop().time() - 2.0
        
        # Set short recovery timeout for test
        breaker.recovery_timeout = 1.0
        
        async def success_func():
            return "recovered"
        
        # First call should transition to HALF_OPEN and succeed
        result = await breaker.call(success_func)
        assert result == "recovered"
        assert breaker.state == CircuitState.HALF_OPEN
    
    @pytest.mark.asyncio
    async def test_circuit_closes_after_successes(self, breaker):
        """Test circuit closes after successful half-open calls."""
        breaker._state = CircuitState.HALF_OPEN
        breaker.half_open_max_calls = 2
        
        async def success_func():
            return "success"
        
        # Make required successful calls
        await breaker.call(success_func)
        await breaker.call(success_func)
        
        assert breaker.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_circuit_reopens_on_half_open_failure(self, breaker):
        """Test circuit reopens if failure during half-open."""
        breaker._state = CircuitState.HALF_OPEN
        
        async def fail_func():
            raise ValueError("Still failing")
        
        with pytest.raises(ValueError):
            await breaker.call(fail_func)
        
        assert breaker.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_decorator_syntax(self, breaker):
        """Test using circuit breaker as decorator."""
        @breaker
        async def decorated_func():
            return "decorated"
        
        result = await decorated_func()
        assert result == "decorated"
    
    def test_get_metrics(self, breaker):
        """Test metrics reporting."""
        metrics = breaker.get_metrics()
        
        assert metrics["name"] == "test_breaker"
        assert metrics["state"] == "CLOSED"
        assert metrics["failure_count"] == 0
