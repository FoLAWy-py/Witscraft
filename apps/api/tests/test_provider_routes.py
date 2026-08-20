from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.config import Settings
from app.llm.router import LLMGateway
from app.llm.model_registry import PURPOSE_DEFAULTS
from app.routers.providers import ModelRoutesRequest, _health_is_fresh
from app.schemas.chat import ChatRequest
from app.schemas.llm import ChatMessage
from app.services.story_engine import StoryEngine


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


def test_client_model_hint_must_match_backend_route() -> None:
    engine = StoryEngine.__new__(StoryEngine)
    engine.llm_gateway = LLMGateway(
        Settings(dry_run_llm=True),
        purpose_routes={"normal_chat": "zai-org/GLM-5.2"},
    )
    messages = [ChatMessage(role="user", content="continue")]

    matching = engine._routed_generation_request(
        ChatRequest(
            message="continue",
            story_id="story",
            provider="deepinfra",
            model="zai-org/GLM-5.2",
        ),
        messages,
        stream=False,
    )
    assert matching.model == "zai-org/GLM-5.2"

    long_chapter = engine._routed_generation_request(
        ChatRequest(message="continue", story_id="story"),
        messages,
        SimpleNamespace(target_chapter_length=5000, chapter_length_unit="words"),
        stream=False,
    )
    assert long_chapter.max_output_tokens == 4096

    with pytest.raises(HTTPException) as caught:
        engine._routed_generation_request(
            ChatRequest(
                message="continue",
                story_id="story",
                provider="deepinfra",
                model="Qwen/Qwen3-Max",
            ),
            messages,
            stream=False,
        )
    assert caught.value.status_code == 409


def test_chat_request_rejects_partial_client_route_hint() -> None:
    with pytest.raises(ValidationError, match="provider and model must be supplied together"):
        ChatRequest(
            message="continue",
            story_id="story",
            provider="deepinfra",
        )
