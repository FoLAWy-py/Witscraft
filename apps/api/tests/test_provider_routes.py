from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.llm.model_registry import PURPOSE_DEFAULTS
from app.routers.providers import ModelRoutesRequest, _health_is_fresh


def test_model_routes_require_every_purpose() -> None:
    routes = dict(PURPOSE_DEFAULTS)
    routes.pop("consistency_check")

    with pytest.raises(ValidationError, match="Missing model routes"):
        ModelRoutesRequest(routes=routes)


def test_model_routes_reject_unknown_models() -> None:
    routes = dict(PURPOSE_DEFAULTS)
    routes["normal_chat"] = "unknown/model"

    with pytest.raises(ValidationError, match="Unknown model"):
        ModelRoutesRequest(routes=routes)


def test_model_routes_accept_registered_defaults() -> None:
    request = ModelRoutesRequest(routes=PURPOSE_DEFAULTS)

    assert request.routes == PURPOSE_DEFAULTS


def test_model_health_freshness_expires_after_six_hours() -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)

    assert _health_is_fresh(now - timedelta(hours=5, minutes=59), now)
    assert not _health_is_fresh(now - timedelta(hours=6, minutes=1), now)


def test_model_health_freshness_normalizes_legacy_naive_timestamps() -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)

    assert _health_is_fresh(datetime(2026, 7, 13, 11), now)
