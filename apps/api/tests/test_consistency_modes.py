import asyncio

import pytest

from app.schemas.chat import StoryState, UpdateStoryRequest
from app.schemas.llm import LLMRequest, LLMResponse
from app.services.context_assembler import ContextAssembly
from app.services.story_engine import StoryEngine


class FakeGateway:
    def __init__(self) -> None:
        self.generate_calls = 0

    def request_for_purpose(self, purpose, messages) -> LLMRequest:
        return LLMRequest(
            provider="deepinfra",
            model="Qwen/Qwen3-Max",
            messages=messages,
            purpose=purpose,
        )

    def normalize_request(self, request: LLMRequest) -> LLMRequest:
        return request

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.generate_calls += 1
        return LLMResponse(
            provider=request.provider,
            model=request.model,
            text="修订后的正文",
        )


class FailingGateway(FakeGateway):
    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.generate_calls += 1
        raise RuntimeError("provider unavailable")


def _engine() -> tuple[StoryEngine, FakeGateway]:
    gateway = FakeGateway()
    engine = StoryEngine.__new__(StoryEngine)
    engine.llm_gateway = gateway
    return engine, gateway


def _context() -> ContextAssembly:
    return ContextAssembly(prompt_messages=[], preview={"sections": {}})


def test_off_mode_skips_consistency_check() -> None:
    engine, gateway = _engine()
    engine._check_consistency = lambda *args: pytest.fail("check should be skipped")

    text, check, revision = asyncio.run(
        engine._apply_consistency_policy("原始正文", StoryState(), _context(), "off")
    )

    assert text == "原始正文"
    assert check["status"] == "off"
    assert revision["reason"] == "checking_disabled"
    assert gateway.generate_calls == 0


def test_manual_mode_returns_conflict_for_confirmation() -> None:
    engine, gateway = _engine()
    failed = {"status": "fail", "issue_count": 1, "issues": [{"rule": "conflict"}]}
    engine._check_consistency = lambda *args: failed

    text, check, revision = asyncio.run(
        engine._apply_consistency_policy("原始正文", StoryState(), _context(), "manual")
    )

    assert text == "原始正文"
    assert check == failed
    assert revision["reason"] == "manual_review"
    assert gateway.generate_calls == 0


def test_auto_mode_replaces_conflicting_text() -> None:
    engine, gateway = _engine()

    def check(text, *_args):
        if text == "原始正文":
            return {"status": "fail", "issue_count": 1, "issues": [{"rule": "conflict"}]}
        return {"status": "pass", "issue_count": 0, "issues": []}

    engine._check_consistency = check
    text, consistency, revision = asyncio.run(
        engine._apply_consistency_policy("原始正文", StoryState(), _context(), "auto")
    )

    assert text == "修订后的正文"
    assert consistency["status"] == "pass"
    assert revision["accepted"] is True
    assert gateway.generate_calls == 1


def test_story_consistency_mode_is_validated() -> None:
    assert UpdateStoryRequest(consistency_mode="auto").consistency_mode == "auto"


def test_auto_mode_falls_back_to_manual_review_when_revision_fails() -> None:
    engine = StoryEngine.__new__(StoryEngine)
    gateway = FailingGateway()
    engine.llm_gateway = gateway
    failed = {"status": "fail", "issue_count": 1, "issues": [{"rule": "conflict"}]}
    engine._check_consistency = lambda *args: failed

    text, consistency, revision = asyncio.run(
        engine._apply_consistency_policy("原始正文", StoryState(), _context(), "auto")
    )

    assert text == "原始正文"
    assert consistency == failed
    assert revision["reason"] == "revision_failed"
    assert gateway.generate_calls == 1
