"""Circuit breaker pattern implementation for external API resilience."""

import asyncio
import time
from enum import Enum, auto
from functools import wraps
from typing import Any, Callable, TypeVar

from src.shared.logger import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = auto()      # Normal operation
    OPEN = auto()        # Failing, reject requests
    HALF_OPEN = auto()   # Testing if recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """Circuit breaker for external API calls.
    
    Example:
        breaker = CircuitBreaker(
            name="deepseek_api",
            failure_threshold=5,
            recovery_timeout=30.0
        )
        
        @breaker
        async def call_api():
            return await http_client.post(...)
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
        expected_exception: type[Exception] = Exception,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.expected_exception = expected_exception
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state
    
    def _can_attempt(self) -> bool:
        """Check if a call can be attempted."""
        if self._state == CircuitState.CLOSED:
            return True
        
        now = time.time()
        if self._state == CircuitState.OPEN:
            if self._last_failure_time and (
                now - self._last_failure_time >= self.recovery_timeout
            ):
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info(f"Circuit {self.name}: transitioning to HALF_OPEN")
                return True
            return False
        
        if self._state == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.half_open_max_calls
        
        return False
    
    def _record_success(self) -> None:
        """Record a successful call."""
        self._failure_count = 0
        
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.half_open_max_calls:
                logger.info(f"Circuit {self.name}: transitioning to CLOSED")
                self._state = CircuitState.CLOSED
                self._success_count = 0
                self._half_open_calls = 0
    
    def _record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        
        if self._state == CircuitState.HALF_OPEN:
            logger.warning(f"Circuit {self.name}: failure in HALF_OPEN, transitioning to OPEN")
            self._state = CircuitState.OPEN
            self._success_count = 0
            self._half_open_calls = 0
        elif self._failure_count >= self.failure_threshold:
            logger.warning(
                f"Circuit {self.name}: failure threshold reached ({self.failure_threshold}), "
                "transitioning to OPEN"
            )
            self._state = CircuitState.OPEN
    
    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute function with circuit breaker protection."""
        async with self._lock:
            if not self._can_attempt():
                raise CircuitBreakerError(
                    f"Circuit breaker '{self.name}' is OPEN"
                )
            
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
        
        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self._record_success()
            return result
        except self.expected_exception as e:
            async with self._lock:
                self._record_failure()
            raise
    
    def __call__(self, func: F) -> F:
        """Decorator for circuit breaker protection."""
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await self.call(func, *args, **kwargs)
        return wrapper  # type: ignore[return-value]
    
    def get_metrics(self) -> dict[str, Any]:
        """Get circuit breaker metrics."""
        return {
            "name": self.name,
            "state": self._state.name,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
            "half_open_calls": self._half_open_calls,
        }


# Global circuit breaker registry
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str) -> CircuitBreaker | None:
    """Get a registered circuit breaker by name."""
    return _circuit_breakers.get(name)


def register_circuit_breaker(breaker: CircuitBreaker) -> None:
    """Register a circuit breaker."""
    _circuit_breakers[breaker.name] = breaker


def create_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    **kwargs: Any,
) -> CircuitBreaker:
    """Create and register a new circuit breaker."""
    breaker = CircuitBreaker(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        **kwargs,
    )
    register_circuit_breaker(breaker)
    return breaker
