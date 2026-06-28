"""Structured logging helpers for Frozbot."""

import datetime
import hashlib
import json
import logging
import os
from typing import Any, Optional


_STANDARD_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}

_REDACTED_FIELD_NAMES = {
    "context",
    "context_string",
    "system_instruction",
    "messages",
    "input",
}


class StructuredFormatter(logging.Formatter):
    """Format log records as JSON with extra fields attached."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.datetime.fromtimestamp(
                record.created, tz=datetime.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_FIELDS or key.startswith("_"):
                continue
            payload[key] = _sanitize_log_value(key, value)

        return json.dumps(payload, ensure_ascii=True, default=str)


def _sanitize_log_value(key: str, value: Any) -> Any:
    if key in _REDACTED_FIELD_NAMES:
        if value is None:
            return None
        text = str(value)
        return {
            "redacted": True,
            "chars": len(text),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        }

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_log_value(key, item) for item in value]
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_log_value(str(item_key), item_value)
            for item_key, item_value in value.items()
        }
    return str(value)


def configure_logging(level_name: Optional[str] = None) -> None:
    """Configure root logging once."""
    level_value = (level_name or os.getenv("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_value, logging.INFO)

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(StructuredFormatter())

    root_logger.setLevel(level)


def context_log_fields(context_string: Optional[str]) -> dict[str, Any]:
    """Return redacted metadata for an LLM context string."""
    if not context_string:
        return {"context_chars": 0, "context_sha256": None}
    return {
        "context_chars": len(context_string),
        "context_sha256": hashlib.sha256(
            context_string.encode("utf-8")
        ).hexdigest()[:16],
    }


def text_log_fields(prefix: str, text: Optional[str]) -> dict[str, Any]:
    """Return non-content metadata for potentially sensitive user text."""
    if not text:
        return {f"{prefix}_chars": 0, f"{prefix}_sha256": None}
    return {
        f"{prefix}_chars": len(text),
        f"{prefix}_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    }


def token_usage_log_fields(token_usage: Any) -> dict[str, int]:
    """Return token usage fields from a TokenUsage-like object."""
    input_tokens = int(getattr(token_usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(token_usage, "output_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
