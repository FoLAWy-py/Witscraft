from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.config import Settings


ACCESS_METRIC_MARKER = "witscraft_access "
LOGGER_NAME = "app.operational_access"


def configure_operational_access_logger(settings: Settings) -> logging.Logger | None:
    configured = settings.operational_metrics_log_path
    if not configured:
        return None
    path = Path(configured)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    resolved = str(path.resolve())
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == resolved:
            return logger

    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    handler = RotatingFileHandler(
        path,
        maxBytes=settings.operational_metrics_log_max_bytes,
        backupCount=settings.operational_metrics_log_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return logger


def route_template(scope: dict[str, Any]) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path.startswith("/"):
        return path[:240]
    return "unmatched"


def log_access_metric(
    logger: logging.Logger | None,
    *,
    request_id: str,
    method: str,
    route: str,
    status_code: int,
    duration_ms: float,
) -> None:
    if logger is None:
        return
    payload = {
        "duration_ms": round(max(0.0, duration_ms), 3),
        "event": "http_request",
        "method": method[:12],
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id[:64],
        "route": route,
        "status_code": status_code,
    }
    logger.info(
        "%s%s",
        ACCESS_METRIC_MARKER,
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
    )
    for handler in logger.handlers:
        handler.flush()


def close_operational_access_logger(logger: logging.Logger | None) -> None:
    if logger is None:
        return
    for handler in list(logger.handlers):
        handler.flush()
        handler.close()
        logger.removeHandler(handler)
