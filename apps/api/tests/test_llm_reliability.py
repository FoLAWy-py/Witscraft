import asyncio
import time

import pytest

from app.config import Settings
from app.llm.audit import CallAuditor
from app.llm.router import LLMGateway, PurposeInputBudgetExceededError, _CIRCUITS
from app.schemas.llm import ChatMessage, LLMRequest, LLMResponse


class CapturingAuditor(CallAuditor):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.rows = []

    async def _persist(self, row) -> bool:
        self.rows.append(row)
        return True


class ModelAwareAdapter:
    def __init__(self, primary_failures: int = 0, error: Exception | None = None):
        self.primary_failures = primary_failures
        self.error = error or asyncio.TimeoutError()
        self.calls: list[str] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request.model)
        if request.model == "test-model" and self.primary_failures > 0:
            self.primary_failures -= 1
            raise self.error
        return LLMResponse(provider=request.provider, model=request.model, text="ok")


class StreamAdapter:
    def __init__(self, *, fail_before_first_chunk: bool = False, fail_after_chunk: bool = False):
        self.fail_before_first_chunk = fail_before_first_chunk
        self.fail_after_chunk = fail_after_chunk
        self.calls = 0

    async def stream(self, _request: LLMRequest):
        self.calls += 1
        if self.fail_before_first_chunk:
            self.fail_before_first_chunk = False
            raise asyncio.TimeoutError()
        yield "first"
        if self.fail_after_chunk:
            raise asyncio.TimeoutError()


def _request() -> LLMRequest:
    return LLMRequest(
        provider="deepinfra",
        model="test-model",
        purpose="state_update",
        messages=[ChatMessage(role="user", content="test")],
        max_output_tokens=128,
    )


def setup_function() -> None:
    _CIRCUITS.clear()


def test_transient_failure_retries_and_audits_each_attempt() -> None:
    settings = Settings(llm_max_attempts=2, llm_max_fallbacks=0, llm_retry_base_seconds=0)
    auditor = CapturingAuditor(settings)
    adapter = ModelAwareAdapter(primary_failures=1)
    gateway = LLMGateway(settings, auditor=auditor)
    gateway.adapters["deepinfra"] = adapter

    response = asyncio.run(gateway.generate(_request()))

    assert response.text == "ok"
    assert adapter.calls == ["test-model", "test-model"]
    assert [(row.attempt, row.status) for row in auditor.rows] == [(1, "failed"), (2, "succeeded")]


def test_non_retryable_failure_is_not_retried_or_fallbacked() -> None:
    settings = Settings(llm_max_attempts=3, llm_max_fallbacks=1, llm_retry_base_seconds=0)
    adapter = ModelAwareAdapter(primary_failures=1, error=ValueError("invalid request"))
    gateway = LLMGateway(settings)
    gateway.adapters["deepinfra"] = adapter

    with pytest.raises(ValueError, match="invalid request"):
        asyncio.run(gateway.generate(_request()))

    assert adapter.calls == ["test-model"]


def test_retry_exhaustion_uses_purpose_fallback() -> None:
    settings = Settings(llm_max_attempts=2, llm_max_fallbacks=1, llm_retry_base_seconds=0)
    adapter = ModelAwareAdapter(primary_failures=2)
    gateway = LLMGateway(settings)
    gateway.adapters["deepinfra"] = adapter

    response = asyncio.run(gateway.generate(_request()))

    assert response.model == "zai-org/GLM-5.2"
    assert adapter.calls == ["test-model", "test-model", "zai-org/GLM-5.2"]


def test_open_circuit_skips_primary_until_cooldown() -> None:
    settings = Settings(
        llm_max_attempts=1,
        llm_max_fallbacks=1,
        llm_retry_base_seconds=0,
        llm_circuit_failure_threshold=1,
    )
    adapter = ModelAwareAdapter(primary_failures=2)
    gateway = LLMGateway(settings)
    gateway.adapters["deepinfra"] = adapter

    asyncio.run(gateway.generate(_request()))
    asyncio.run(gateway.generate(_request()))

    assert adapter.calls == ["test-model", "zai-org/GLM-5.2", "zai-org/GLM-5.2"]


def test_half_open_circuit_allows_only_one_probe() -> None:
    settings = Settings(
        llm_max_attempts=1,
        llm_max_fallbacks=0,
        llm_circuit_failure_threshold=1,
    )
    gateway = LLMGateway(settings)
    request = _request()
    gateway._record_circuit_failure(request)
    _CIRCUITS[(request.provider, request.model)].opened_until = time.monotonic() - 0.01

    assert gateway._circuit_is_open(request) is False
    assert gateway._circuit_is_open(request) is True

    gateway._record_circuit_success(request)
    assert gateway._circuit_is_open(request) is False


def test_stream_retries_only_before_first_visible_chunk() -> None:
    settings = Settings(llm_max_attempts=2, llm_max_fallbacks=0, llm_retry_base_seconds=0)
    adapter = StreamAdapter(fail_before_first_chunk=True)
    gateway = LLMGateway(settings)
    gateway.adapters["deepinfra"] = adapter

    async def collect() -> list[str]:
        return [chunk async for chunk in gateway.stream(_request())]

    assert asyncio.run(collect()) == ["first"]
    assert adapter.calls == 2


def test_stream_does_not_retry_after_first_visible_chunk() -> None:
    settings = Settings(llm_max_attempts=2, llm_max_fallbacks=1, llm_retry_base_seconds=0)
    adapter = StreamAdapter(fail_after_chunk=True)
    gateway = LLMGateway(settings)
    gateway.adapters["deepinfra"] = adapter

    async def collect() -> list[str]:
        return [chunk async for chunk in gateway.stream(_request())]

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(collect())
    assert adapter.calls == 1


def test_purpose_budget_sets_default_and_clamps_explicit_output() -> None:
    gateway = LLMGateway(Settings())
    default_request = gateway.request_for_purpose(
        "state_update",
        [ChatMessage(role="user", content="test")],
    )
    oversized = default_request.model_copy(update={"max_output_tokens": 9000})

    assert default_request.max_output_tokens == 1000
    assert gateway.normalize_request(oversized).max_output_tokens == 1800


def test_input_budget_rejects_request_before_provider_call() -> None:
    settings = Settings(llm_max_fallbacks=0)
    adapter = ModelAwareAdapter()
    gateway = LLMGateway(settings)
    gateway.adapters["deepinfra"] = adapter
    request = _request().model_copy(
        update={"messages": [ChatMessage(role="user", content="长" * 8001)]}
    )

    with pytest.raises(PurposeInputBudgetExceededError, match="state_update"):
        asyncio.run(gateway.generate(request))

    assert adapter.calls == []
