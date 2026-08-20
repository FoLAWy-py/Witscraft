import asyncio
from types import SimpleNamespace

import pytest

from app.schemas.llm import ChatMessage, LLMRequest, LLMResponse
from app.services.player_agency import (
    chapter_needs_expansion,
    chapter_authoring_instruction,
    ensure_chapter_heading,
    measured_chapter_length,
    reject_known_impossible_action,
)
from app.services.story_engine import StoryEngine


class AgencyGateway:
    def __init__(self, responses: list[str] | None = None, error: Exception | None = None):
        self.responses = list(responses or [])
        self.error = error
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return LLMResponse(
            provider=request.provider,
            model=request.model,
            text=self.responses.pop(0),
        )


def _agency_request() -> LLMRequest:
    return LLMRequest(
        provider="deepinfra",
        model="Qwen/Qwen3-Max",
        purpose="normal_chat",
        messages=[ChatMessage(role="user", content="I wait.")],
        max_output_tokens=2400,
    )


def test_normal_turn_preserves_protagonist_control() -> None:
    instruction = chapter_authoring_instruction(
        control_mode="player_action",
        chapter_number=4,
        chapter_title="The Locked Gate",
        chapter_objective="Reveal the cost of entry.",
        target_length=1800,
        length_unit="words",
        prose_language="en",
        player_action="I wait beside the gate.",
    )
    assert "player controls the protagonist" in instruction
    assert "private thoughts" in instruction
    assert "exhaustive whitelist" in instruction
    assert "I wait beside the gate." in instruction
    assert "silently delete" in instruction
    assert "quoted dialogue" in instruction
    assert "NPC dialogue and reactions" in instruction
    assert "approximately 1800" in instruction


def test_continue_delegates_exactly_one_reversible_turn() -> None:
    instruction = chapter_authoring_instruction(
        control_mode="continue",
        chapter_number=2,
        chapter_title="潮声",
        chapter_objective="推进线索。",
        target_length=1800,
        length_unit="characters",
        prose_language="zh-CN",
    )
    assert "for this chapter only" in instruction
    assert "delegation expires after this reply" in instruction
    assert "irreversible commitment" in instruction


def test_explicit_impossible_action_is_rejected_with_rule_reason() -> None:
    rejection = reject_known_impossible_action(
        "I teleport through the sealed gate.",
        {
            "impossible_actions": [
                {"action": "teleport", "reason": "Teleportation does not exist in this world."}
            ]
        },
    )
    assert rejection is not None
    assert rejection.reason == "Teleportation does not exist in this world."
    assert reject_known_impossible_action("I inspect the gate.", {"impossible_actions": []}) is None


def test_canonical_chapter_heading_is_idempotent() -> None:
    titled = ensure_chapter_heading("The gate opens.", 3, "The Last Lock")
    assert titled.startswith("## 3. The Last Lock\n\n")
    assert ensure_chapter_heading(titled, 3, "The Last Lock") == titled


def test_chapter_length_uses_player_facing_units_and_fifteen_percent_floor() -> None:
    assert measured_chapter_length("潮 声\n又近了。", "characters") == 6
    assert measured_chapter_length("Three precise words", "words") == 3
    assert chapter_needs_expansion("潮" * 424, 500, "characters") is True
    assert chapter_needs_expansion("潮" * 425, 500, "characters") is False


def test_agency_editor_uses_openai_and_trims_only_an_overlong_result() -> None:
    gateway = AgencyGateway([" ".join(["draft"] * 120), " ".join(["trimmed"] * 100)])
    engine = StoryEngine.__new__(StoryEngine)
    engine.llm_gateway = gateway

    revised, response = asyncio.run(
        engine._enforce_player_agency(
            "original",
            story=SimpleNamespace(target_chapter_length=100, chapter_length_unit="words"),
            request=SimpleNamespace(control_mode="player_action", message="I wait."),
            chapter=SimpleNamespace(),
            llm_request=_agency_request(),
        )
    )

    assert measured_chapter_length(revised, "words") == 100
    assert response is not None
    assert len(gateway.requests) == 2
    assert gateway.requests[0].provider == "openai"
    assert gateway.requests[0].model == "gpt-5.5"
    assert gateway.requests[0].purpose == "consistency_check"
    assert gateway.requests[1].reasoning_effort == "low"


def test_agency_editor_fails_closed_when_provider_edit_fails() -> None:
    gateway = AgencyGateway(error=RuntimeError("provider unavailable"))
    engine = StoryEngine.__new__(StoryEngine)
    engine.llm_gateway = gateway

    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(
            engine._enforce_player_agency(
                "unreviewed",
                story=SimpleNamespace(target_chapter_length=100, chapter_length_unit="words"),
                request=SimpleNamespace(control_mode="player_action", message="I wait."),
                chapter=SimpleNamespace(),
                llm_request=_agency_request(),
            )
        )
