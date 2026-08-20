import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.operational_logging import ACCESS_METRIC_MARKER


def _events(path: Path) -> list[dict]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        assert line.startswith(ACCESS_METRIC_MARKER)
        events.append(json.loads(line.removeprefix(ACCESS_METRIC_MARKER)))
    return events


def test_access_metrics_use_route_templates_and_exclude_request_data(tmp_path: Path) -> None:
    metrics_path = tmp_path / "access-metrics.log"
    application = create_app(
        Settings(
            dry_run_llm=True,
            operational_metrics_log_path=str(metrics_path),
            operational_metrics_log_max_bytes=100_000,
        )
    )
    with TestClient(application) as client:
        health = client.get("/health", headers={"X-Request-ID": "metrics-request-1"})
        missing = client.get("/private-story-id?token=do-not-log-this")

    assert health.status_code == 200
    assert missing.status_code == 404
    events = _events(metrics_path)
    assert len(events) == 2
    assert events[0] == {
        "duration_ms": events[0]["duration_ms"],
        "event": "http_request",
        "method": "GET",
        "observed_at": events[0]["observed_at"],
        "request_id": "metrics-request-1",
        "route": "/health",
        "status_code": 200,
    }
    assert events[1]["route"] == "unmatched"
    serialized = metrics_path.read_text(encoding="utf-8")
    assert "private-story-id" not in serialized
    assert "do-not-log-this" not in serialized
    assert metrics_path.stat().st_mode & 0o777 == 0o600


def test_operational_metrics_path_must_be_absolute() -> None:
    with pytest.raises(ValidationError, match="must be absolute"):
        Settings(operational_metrics_log_path="relative/access.log")
