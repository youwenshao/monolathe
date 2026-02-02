"""Loki logging integration for centralized log aggregation.

Sends structured logs to Loki for Grafana visualization.
"""

import asyncio
import json
import queue
import threading
import time
from typing import Any

import httpx

from src.shared.config import get_settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


class LokiLogHandler:
    """Async log handler for Loki."""
    
    def __init__(
        self,
        loki_url: str = "http://localhost:3100",
        batch_size: int = 100,
        flush_interval: float = 5.0,
    ):
        self.loki_url = loki_url
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._log_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._buffer: list[dict[str, Any]] = []
        self._running = False
        self._flush_thread: threading.Thread | None = None
        self._client: httpx.AsyncClient | None = None
        
        # Default labels
        self.default_labels = {
            "service": "monolathe",
            "environment": get_settings().environment,
        }
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.loki_url,
                timeout=10.0,
            )
        return self._client
    
    def start(self) -> None:
        """Start background flush thread."""
        self._running = True
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()
        logger.info("Loki log handler started")
    
    def stop(self) -> None:
        """Stop handler and flush remaining logs."""
        self._running = False
        
        # Flush remaining logs
        self._flush_sync()
        
        if self._flush_thread:
            self._flush_thread.join(timeout=10)
    
    def emit(self, log_record: dict[str, Any]) -> None:
        """Add log record to queue.
        
        Args:
            log_record: Structured log record
        """
        # Enrich with timestamp
        log_record["ts"] = time.time_ns()
        
        self._log_queue.put(log_record)
    
    def _flush_loop(self) -> None:
        """Background thread to periodically flush logs."""
        while self._running:
            try:
                # Collect logs from queue
                while len(self._buffer) < self.batch_size:
                    try:
                        record = self._log_queue.get(timeout=0.1)
                        self._buffer.append(record)
                    except queue.Empty:
                        break
                
                # Flush if buffer full or interval reached
                if len(self._buffer) >= self.batch_size:
                    self._flush_sync()
                
                time.sleep(self.flush_interval)
                
            except Exception as e:
                logger.error(f"Loki flush error: {e}")
    
    def _flush_sync(self) -> None:
        """Synchronous flush for use in background thread."""
        if not self._buffer:
            return
        
        logs_to_send = self._buffer[:self.batch_size]
        self._buffer = self._buffer[self.batch_size:]
        
        # Run async flush in new event loop
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self._send_logs(logs_to_send))
            loop.close()
        except Exception as e:
            logger.error(f"Failed to send logs to Loki: {e}")
            # Put back in buffer for retry
            self._buffer.extend(logs_to_send)
    
    async def _send_logs(self, logs: list[dict[str, Any]]) -> None:
        """Send logs to Loki.
        
        Args:
            logs: List of log records
        """
        if not logs:
            return
        
        try:
            client = await self._get_client()
            
            # Format for Loki push API
            streams = []
            
            # Group by labels
            for log in logs:
                labels = self.default_labels.copy()
                labels.update(log.get("labels", {}))
                
                stream = {
                    "stream": labels,
                    "values": [
                        [str(log["ts"]), json.dumps(log)],
                    ],
                }
                streams.append(stream)
            
            payload = {"streams": streams}
            
            response = await client.post(
                "/loki/api/v1/push",
                json=payload,
            )
            response.raise_for_status()
            
        except Exception as e:
            logger.error(f"Loki push failed: {e}")
            raise


class StructuredLogger:
    """Structured logger with trace context."""
    
    def __init__(self, service: str, loki_handler: LokiLogHandler | None = None):
        self.service = service
        self.loki = loki_handler
    
    def _make_record(
        self,
        level: str,
        message: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create structured log record.
        
        Args:
            level: Log level
            message: Log message
            **kwargs: Additional fields
            
        Returns:
            Structured record
        """
        import uuid
        
        record = {
            "service": self.service,
            "level": level,
            "message": message,
            "timestamp": time.time(),
            "trace_id": kwargs.get("trace_id", str(uuid.uuid4())[:8]),
        }
        
        # Add optional fields
        if "channel_id" in kwargs:
            record["channel_id"] = kwargs["channel_id"]
        if "content_id" in kwargs:
            record["content_id"] = kwargs["content_id"]
        if "duration_ms" in kwargs:
            record["duration_ms"] = kwargs["duration_ms"]
        if "error" in kwargs:
            record["error"] = str(kwargs["error"])
        
        return record
    
    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        record = self._make_record("DEBUG", message, **kwargs)
        if self.loki:
            self.loki.emit(record)
    
    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        record = self._make_record("INFO", message, **kwargs)
        if self.loki:
            self.loki.emit(record)
        # Also log to standard logger
        logger.info(message, extra=kwargs)
    
    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        record = self._make_record("WARNING", message, **kwargs)
        if self.loki:
            self.loki.emit(record)
        logger.warning(message, extra=kwargs)
    
    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        record = self._make_record("ERROR", message, **kwargs)
        if self.loki:
            self.loki.emit(record)
        logger.error(message, extra=kwargs)
    
    def critical(self, message: str, **kwargs: Any) -> None:
        """Log critical message."""
        record = self._make_record("CRITICAL", message, **kwargs)
        if self.loki:
            self.loki.emit(record)
        logger.critical(message, extra=kwargs)


# Global Loki handler instance
_loki_handler: LokiLogHandler | None = None


def init_loki_logging(loki_url: str = "http://localhost:3100") -> LokiLogHandler:
    """Initialize Loki logging.
    
    Args:
        loki_url: Loki server URL
        
    Returns:
        Loki handler instance
    """
    global _loki_handler
    _loki_handler = LokiLogHandler(loki_url=loki_url)
    _loki_handler.start()
    return _loki_handler


def get_loki_logger(service: str) -> StructuredLogger:
    """Get structured logger for service.
    
    Args:
        service: Service name
        
    Returns:
        Structured logger
    """
    return StructuredLogger(service, _loki_handler)


def shutdown_loki() -> None:
    """Shutdown Loki logging."""
    global _loki_handler
    if _loki_handler:
        _loki_handler.stop()
        _loki_handler = None