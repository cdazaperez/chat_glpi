"""
Structured logging configuration for Helpdesk AI.
Implements JSON logging with correlation IDs and PII masking.
"""
import logging
import sys
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from contextvars import ContextVar

# Context variable for correlation ID
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Get the current correlation ID."""
    return correlation_id_var.get()


def set_correlation_id(correlation_id: Optional[str] = None) -> str:
    """Set a new correlation ID (generates one if not provided)."""
    cid = correlation_id or str(uuid.uuid4())
    correlation_id_var.set(cid)
    return cid


class PIIMasker:
    """Masks PII and sensitive data from log messages."""

    # Patterns to mask
    PATTERNS = [
        # Email addresses
        (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL_MASKED]'),
        # Phone numbers (various formats)
        (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE_MASKED]'),
        # Credit card numbers
        (r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b', '[CC_MASKED]'),
        # SSN
        (r'\b\d{3}[-]?\d{2}[-]?\d{4}\b', '[SSN_MASKED]'),
        # API keys (common patterns)
        (r'sk-[a-zA-Z0-9]{32,}', '[API_KEY_MASKED]'),
        (r'Bearer\s+[a-zA-Z0-9._-]+', 'Bearer [TOKEN_MASKED]'),
        # Passwords in URLs
        (r'password[=:][^&\s]+', 'password=[MASKED]'),
        # Generic tokens
        (r'token[=:][^&\s]+', 'token=[MASKED]'),
    ]

    @classmethod
    def mask(cls, text: str) -> str:
        """Mask PII and sensitive data in text."""
        if not isinstance(text, str):
            return text

        result = text
        for pattern, replacement in cls.PATTERNS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result

    @classmethod
    def mask_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively mask PII in a dictionary."""
        if not isinstance(data, dict):
            return data

        result = {}
        sensitive_keys = {'password', 'token', 'api_key', 'apikey', 'secret', 'authorization'}

        for key, value in data.items():
            lower_key = key.lower()
            if any(s in lower_key for s in sensitive_keys):
                result[key] = '[REDACTED]'
            elif isinstance(value, dict):
                result[key] = cls.mask_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    cls.mask_dict(item) if isinstance(item, dict)
                    else cls.mask(str(item)) if isinstance(item, str)
                    else item
                    for item in value
                ]
            elif isinstance(value, str):
                result[key] = cls.mask(value)
            else:
                result[key] = value
        return result


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": PIIMasker.mask(record.getMessage()),
            "correlation_id": get_correlation_id() or None,
        }

        # Add location info
        if record.pathname:
            log_entry["location"] = {
                "file": record.pathname.split("/")[-1],
                "line": record.lineno,
                "function": record.funcName,
            }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": PIIMasker.mask(str(record.exc_info[1])) if record.exc_info[1] else None,
            }

        # Add extra fields (masked)
        if hasattr(record, "extra_data"):
            log_entry["data"] = PIIMasker.mask_dict(record.extra_data)

        return json.dumps(log_entry, default=str)


class StructuredLogger(logging.Logger):
    """Custom logger with structured logging support."""

    def _log_with_extra(
        self,
        level: int,
        msg: str,
        args: tuple,
        exc_info: Any = None,
        extra: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """Log with extra data support."""
        if extra is None:
            extra = {}

        # Store extra data for the formatter
        extra["extra_data"] = kwargs.get("data", {})

        super()._log(level, msg, args, exc_info=exc_info, extra=extra)

    def debug(self, msg: str, *args, data: Optional[Dict[str, Any]] = None, **kwargs):
        self._log_with_extra(logging.DEBUG, msg, args, data=data or {}, **kwargs)

    def info(self, msg: str, *args, data: Optional[Dict[str, Any]] = None, **kwargs):
        self._log_with_extra(logging.INFO, msg, args, data=data or {}, **kwargs)

    def warning(self, msg: str, *args, data: Optional[Dict[str, Any]] = None, **kwargs):
        self._log_with_extra(logging.WARNING, msg, args, data=data or {}, **kwargs)

    def error(self, msg: str, *args, data: Optional[Dict[str, Any]] = None, **kwargs):
        self._log_with_extra(logging.ERROR, msg, args, data=data or {}, **kwargs)

    def critical(self, msg: str, *args, data: Optional[Dict[str, Any]] = None, **kwargs):
        self._log_with_extra(logging.CRITICAL, msg, args, data=data or {}, **kwargs)


# Set the custom logger class immediately so all loggers created via get_logger()
# will be StructuredLogger instances, even before setup_logging() is called
logging.setLoggerClass(StructuredLogger)


def setup_logging(log_level: str = "info") -> None:
    """Set up structured logging."""
    # Get the root logger
    root_logger = logging.getLogger()

    # Set log level
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create console handler with JSON formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(JSONFormatter())
    root_logger.addHandler(console_handler)

    # Suppress noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance."""
    return logging.getLogger(name)
