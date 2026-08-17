import asyncio

import pytest

from app.schemas.chat import StoryState, UpdateStoryRequest
from app.schemas.llm import LLMRequest, LLMResponse
from app.services.consistency_checker import check_response_consistency
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


def _check(*, errors: int = 0, warnings: int = 0) -> dict:
    issues = [
        {"rule": f"error-{index}", "severity": "error"}
        for index in range(errors)
    ] + [
        {"rule": f"warning-{index}", "severity": "warning"}
        for index in range(warnings)
    ]
    return {
        "status": "fail" if errors else "pass",
        "issue_count": len(issues),
        "error_count": errors,
        "warning_count": warnings,
        "highest_severity": "error" if errors else "warning" if warnings else None,
        "issues": issues,
    }


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
    failed = _check(errors=1)
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
            return _check(errors=1)
        return _check()

    engine._check_consistency = check
    text, consistency, revision = asyncio.run(
        engine._apply_consistency_policy("原始正文", StoryState(), _context(), "auto")
    )

    assert text == "修订后的正文"
    assert consistency["status"] == "pass"
    assert revision["accepted"] is True
    assert revision["trigger"] == "high_severity_local_rule"
    assert revision["initial_error_count"] == 1
    assert revision["final_error_count"] == 0
    assert gateway.generate_calls == 1


def test_auto_mode_keeps_warning_local_without_revision_call() -> None:
    engine, gateway = _engine()
    warning = _check(warnings=1)
    engine._check_consistency = lambda *args: warning

    text, consistency, revision = asyncio.run(
        engine._apply_consistency_policy("原始正文", StoryState(), _context(), "auto")
    )

    assert text == "原始正文"
    assert consistency == warning
    assert revision["reason"] == "check_passed"
    assert gateway.generate_calls == 0


def test_auto_mode_rejects_revision_that_retains_high_severity_error() -> None:
    engine, gateway = _engine()
    engine._check_consistency = lambda *args: _check(errors=1)

    text, consistency, revision = asyncio.run(
        engine._apply_consistency_policy("原始正文", StoryState(), _context(), "auto")
    )

    assert text == "原始正文"
    assert consistency["error_count"] == 1
    assert revision["accepted"] is False
    assert revision["reason"] == "kept_original"
    assert revision["final_error_count"] == 1
    assert gateway.generate_calls == 1


def test_story_consistency_mode_is_validated() -> None:
    assert UpdateStoryRequest(consistency_mode="auto").consistency_mode == "auto"


def test_auto_mode_falls_back_to_manual_review_when_revision_fails() -> None:
    engine = StoryEngine.__new__(StoryEngine)
    gateway = FailingGateway()
    engine.llm_gateway = gateway
    failed = _check(errors=1)
    engine._check_consistency = lambda *args: failed

    text, consistency, revision = asyncio.run(
        engine._apply_consistency_policy("原始正文", StoryState(), _context(), "auto")
    )

    assert text == "原始正文"
    assert consistency == failed
    assert revision["reason"] == "revision_failed"
    assert gateway.generate_calls == 1


def test_local_consistency_result_separates_errors_and_warnings() -> None:
    error = check_response_consistency(
        "林岚忽然复活，重新站了起来。",
        StoryState(),
        ["林岚已经死亡"],
        {},
        {},
    )
    assert error["status"] == "fail"
    assert error["error_count"] == 1
    assert error["warning_count"] == 0
    assert error["highest_severity"] == "error"

    warning = check_response_consistency(
        "守门人开始飞行。",
        StoryState(),
        [],
        {},
        {"rules": {"travel": "禁止飞行"}},
    )
    assert warning["status"] == "pass"
    assert warning["error_count"] == 0
    assert warning["warning_count"] == 1
    assert warning["highest_severity"] == "warning"
