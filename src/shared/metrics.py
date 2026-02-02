"""Prometheus metrics collection for Monolathe.

Provides comprehensive monitoring for the entire pipeline.
"""

import functools
import time
from contextlib import contextmanager
from typing import Any, Callable

from prometheus_client import Counter, Gauge, Histogram, Info, start_http_server

from src.shared.config import get_settings
from src.shared.logger import get_logger

logger = get_logger(__name__)

# =============================================================================
# System Information
# =============================================================================

SYSTEM_INFO = Info("monolathe_build", "Build information")

# =============================================================================
# Generation Metrics
# =============================================================================

GENERATION_DURATION = Histogram(
    "generation_duration_seconds",
    "Time spent generating assets",
    ["type", "model", "status"],
    buckets=[5, 10, 30, 60, 120, 180, 300, 600],
)

GENERATION_VRAM = Gauge(
    "generation_vram_usage_gb",
    "VRAM usage during generation",
    ["type"],
)

GENERATION_QUEUE_DEPTH = Gauge(
    "generation_queue_depth",
    "Number of jobs waiting in generation queue",
    ["type"],
)

GENERATION_CONCURRENT = Gauge(
    "generation_concurrent_jobs",
    "Number of concurrent generation jobs",
    ["type"],
)

# =============================================================================
# Upload Metrics
# =============================================================================

UPLOAD_DURATION = Histogram(
    "upload_duration_seconds",
    "Time spent uploading to Instagram",
    ["channel_id", "status"],
    buckets=[10, 30, 60, 120, 300, 600],
)

UPLOAD_QUEUE_DEPTH = Gauge(
    "upload_queue_depth",
    "Number of videos waiting to upload",
)

UPLOAD_QUEUE_WAIT = Histogram(
    "upload_queue_wait_seconds",
    "Time spent waiting in upload queue",
    buckets=[60, 300, 600, 1800, 3600],
)

UPLOAD_TOTAL = Counter(
    "videos_uploaded_total",
    "Total number of videos uploaded",
    ["channel_id", "platform", "status"],
)

UPLOAD_RETRIES = Counter(
    "upload_retries_total",
    "Total number of upload retries",
    ["channel_id"],
)

# =============================================================================
# API Metrics
# =============================================================================

API_LATENCY = Histogram(
    "api_response_time_seconds",
    "API response time",
    ["endpoint", "method", "status"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0],
)

API_REQUESTS_TOTAL = Counter(
    "api_requests_total",
    "Total API requests",
    ["endpoint", "method", "status"],
)

INSTAGRAM_API_LATENCY = Histogram(
    "instagram_api_latency_seconds",
    "Instagram API call latency",
    ["operation", "status"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

# =============================================================================
# Circuit Breaker Metrics
# =============================================================================

CIRCUIT_BREAKER_STATE = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=half-open, 2=open)",
    ["name"],
)

CIRCUIT_BREAKER_FAILURES = Counter(
    "circuit_breaker_failures_total",
    "Total failures tripping circuit breaker",
    ["name"],
)

# =============================================================================
# Channel Metrics
# =============================================================================

CHANNEL_CONTAINERS = Gauge(
    "channel_container_count",
    "Number of active channel containers",
)

CHANNEL_POSTS = Counter(
    "channel_posts_total",
    "Total posts per channel",
    ["channel_id", "niche"],
)

CHANNEL_FINGERPRINT_ROTATIONS = Counter(
    "channel_fingerprint_rotations_total",
    "Number of fingerprint rotations",
    ["channel_id"],
)

# =============================================================================
# Compliance Metrics
# =============================================================================

COMPLIANCE_VIOLATIONS = Counter(
    "compliance_violations_total",
    "Total compliance violations",
    ["channel_id", "type", "action"],
)

COMPLIANCE_CHECKS = Counter(
    "compliance_checks_total",
    "Total compliance checks performed",
    ["type", "result"],
)

KILL_SWITCH_ACTIVE = Gauge(
    "kill_switch_active",
    "Whether kill switch is active (0/1)",
    ["scope"],
)

# =============================================================================
# Resource Metrics
# =============================================================================

VRAM_USAGE_PERCENT = Gauge(
    "vram_usage_percent",
    "VRAM usage percentage",
)

CPU_USAGE_PERCENT = Gauge(
    "cpu_usage_percent",
    "CPU usage percentage",
)

MEMORY_USAGE_PERCENT = Gauge(
    "memory_usage_percent",
    "Memory usage percentage",
)

DISK_USAGE_PERCENT = Gauge(
    "disk_usage_percent",
    "Disk usage percentage",
    ["mount"],
)

# =============================================================================
# Business Metrics
# =============================================================================

CONTENT_THROUGHPUT = Counter(
    "content_throughput_total",
    "Total content pieces processed",
    ["stage"],
)

COST_PER_VIDEO = Gauge(
    "cost_per_video_usd",
    "Calculated cost per video",
    ["channel_id"],
)

DAILY_TARGET_PROGRESS = Gauge(
    "daily_target_progress",
    "Progress toward daily target (0-1)",
)

# =============================================================================
# Decorators and Helpers
# =============================================================================

def timed(metric: Histogram, labels: dict[str, str] | None = None) -> Callable:
    """Decorator to time function execution.
    
    Args:
        metric: Histogram to record duration
        labels: Additional labels
        
    Example:
        @timed(GENERATION_DURATION, {"type": "voice"})
        async def generate_voice():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            start = time.time()
            status = "success"
            try:
                return await func(*args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                duration = time.time() - start
                metric_labels = (labels or {}).copy()
                metric_labels["status"] = status
                metric.labels(**metric_labels).observe(duration)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            start = time.time()
            status = "success"
            try:
                return func(*args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                duration = time.time() - start
                metric_labels = (labels or {}).copy()
                metric_labels["status"] = status
                metric.labels(**metric_labels).observe(duration)
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


def count(metric: Counter, labels: dict[str, str] | None = None) -> Callable:
    """Decorator to count function calls."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            metric.labels(**(labels or {})).inc()
            return await func(*args, **kwargs)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            metric.labels(**(labels or {})).inc()
            return func(*args, **kwargs)
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


@contextmanager
def measure_duration(metric: Histogram, labels: dict[str, str] | None = None):
    """Context manager to measure duration.
    
    Example:
        with measure_duration(GENERATION_DURATION, {"type": "image"}):
            await generate_image()
    """
    start = time.time()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        duration = time.time() - start
        metric_labels = (labels or {}).copy()
        metric_labels["status"] = status
        metric.labels(**metric_labels).observe(duration)


# =============================================================================
# Metrics Server
# =============================================================================

def start_metrics_server(port: int = 9090) -> None:
    """Start Prometheus metrics HTTP server.
    
    Args:
        port: Port to expose metrics on
    """
    import os
    
    # Set build info
    SYSTEM_INFO.info({
        "version": "0.4.0",
        "phase": "4",
        "platform": "instagram_reels",
    })
    
    try:
        start_http_server(port)
        logger.info(f"Metrics server started on port {port}")
    except Exception as e:
        logger.error(f"Failed to start metrics server: {e}")


# =============================================================================
# System Resource Collection
# =============================================================================

import psutil
import asyncio

async def collect_system_metrics() -> None:
    """Periodically collect system resource metrics."""
    while True:
        try:
            # CPU
            CPU_USAGE_PERCENT.set(psutil.cpu_percent(interval=1))
            
            # Memory
            mem = psutil.virtual_memory()
            MEMORY_USAGE_PERCENT.set(mem.percent)
            
            # Disk
            for partition in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    DISK_USAGE_PERCENT.labels(mount=partition.mountpoint).set(usage.percent)
                except PermissionError:
                    continue
            
            # VRAM (macOS unified memory approximation)
            vram_used = (mem.total - mem.available) / (1024 ** 3)
            vram_percent = (vram_used / 48.0) * 100  # Assuming 48GB system
            VRAM_USAGE_PERCENT.set(vram_percent)
            
        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")
        
        await asyncio.sleep(15)  # Collect every 15 seconds


def run_metrics_collection() -> None:
    """Start background metrics collection."""
    asyncio.create_task(collect_system_metrics())