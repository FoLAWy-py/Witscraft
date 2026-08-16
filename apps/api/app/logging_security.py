from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any


REDACTED = "[REDACTED]"
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "content",
    "cookie",
    "messages",
    "password",
    "prompt",
    "prompt_text",
    "secret",
    "set_cookie",
    "smtp_password",
    "token",
}

_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_TOKEN_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_QUERY_PATTERN = re.compile(
    r"(?i)([?&](?:api[_-]?key|authorization|cookie|password|prompt|reset_password|"
    r"secret|token|verify_email)=)([^&\s]*)"
)
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|authorization|cookie|password|prompt|secret|"
    r"smtp_password|token)\b\s*[:=]\s*)([\"']?)([^\s,;&}\]]+)([\"']?)"
)


def redact_sensitive_text(value: str) -> str:
    redacted = _BEARER_PATTERN.sub(f"Bearer {REDACTED}", value)
    redacted = _SECRET_TOKEN_PATTERN.sub(REDACTED, redacted)
    redacted = _ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}{match.group(4)}",
        redacted,
    )
    return _QUERY_PATTERN.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)


def redact_log_value(value: Any, *, key: str | None = None) -> Any:
    if key and key.lower().replace("-", "_") in SENSITIVE_KEYS:
        return REDACTED
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, Mapping):
        return {item_key: redact_log_value(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(redact_log_value(item) for item in value)
    if isinstance(value, list):
        return [redact_log_value(item) for item in value]
    return value


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_text(record.msg)
        record.args = redact_log_value(record.args)
        return True


def install_sensitive_log_filters() -> None:
    loggers = [logging.getLogger()]
    loggers.extend(
        logging.getLogger(name)
        for name in ("app", "uvicorn", "uvicorn.access", "uvicorn.error")
    )
    for logger in loggers:
        if not any(isinstance(item, SensitiveDataFilter) for item in logger.filters):
            logger.addFilter(SensitiveDataFilter())
        for handler in logger.handlers:
            if not any(isinstance(item, SensitiveDataFilter) for item in handler.filters):
                handler.addFilter(SensitiveDataFilter())
