import asyncio

import pytest

from app.schemas.llm import ChatMessage, LLMRequest, LLMResponse
from app.services.story_engine import StoryEngine, merge_story_continuation


class FakeGateway:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return self.responses.pop(0)


def _response(text: str, status: str = "completed") -> LLMResponse:
    return LLMResponse(
        provider="deepinfra",
        model="Qwen/Qwen3-Max",
        text=text,
        completion_status=status,
        finish_reason="length" if status == "length_limited" else "stop",
    )


def _request() -> LLMRequest:
    return LLMRequest(
        provider="deepinfra",
        model="Qwen/Qwen3-Max",
        messages=[ChatMessage(role="user", content="我检查信封。")],
    )


def _engine(gateway: FakeGateway) -> StoryEngine:
    engine = StoryEngine.__new__(StoryEngine)
    engine.llm_gateway = gateway
    return engine


def test_completed_narrative_needs_no_continuation() -> None:
    gateway = FakeGateway([])
    primary = _response("完整场景。")

    result = asyncio.run(
        _engine(gateway)._ensure_complete_narrative_response(_request(), primary)
    )

    assert result is primary
    assert gateway.requests == []


def test_length_limited_narrative_gets_one_bounded_continuation() -> None:
    gateway = FakeGateway([_response("门终于打开，决定权回到你手中。")])
    primary = _response("雨声压住脚步。", "length_limited")

    result = asyncio.run(
        _engine(gateway)._ensure_complete_narrative_response(_request(), primary)
    )

    assert result.text == "雨声压住脚步。\n\n门终于打开，决定权回到你手中。"
    assert result.completion_status == "completed"
    assert result.raw["continued_after_length_limit"] is True
    assert len(gateway.requests) == 1
    assert gateway.requests[0].stream is False
    assert "Do not recap" in gateway.requests[0].messages[-1].content


def test_second_length_limit_fails_closed_without_persistable_text() -> None:
    gateway = FakeGateway([_response("仍未结束", "length_limited")])

    with pytest.raises(RuntimeError, match="still incomplete"):
        asyncio.run(
            _engine(gateway)._ensure_complete_narrative_response(
                _request(), _response("被截断", "length_limited")
            )
        )


def test_non_length_interruption_is_not_guessed_or_continued() -> None:
    gateway = FakeGateway([])

    with pytest.raises(RuntimeError, match="incomplete response"):
        asyncio.run(
            _engine(gateway)._ensure_complete_narrative_response(
                _request(), _response("部分正文", "interrupted")
            )
        )
    assert gateway.requests == []


def test_continuation_overlap_is_removed_once() -> None:
    assert merge_story_continuation(
        "灯光逐渐暗下，门外传来三声敲击。",
        "门外传来三声敲击。林岚抬起头。",
    ) == "灯光逐渐暗下，门外传来三声敲击。林岚抬起头。"
