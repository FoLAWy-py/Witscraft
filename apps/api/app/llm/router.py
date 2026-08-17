import asyncio
import random
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from app.config import Settings
from app.llm.audit import CallAuditor
from app.llm.deepinfra_adapter import DeepInfraAdapter
from app.llm.model_registry import choose_model, fallback_models, get_model, purpose_budget
from app.llm.openai_adapter import OpenAIAdapter
from app.schemas.llm import LLMRequest, LLMResponse, StoryPurpose


@dataclass
class _CircuitState:
    failures: int = 0
    opened_until: float = 0
    half_open_in_flight: bool = False


class CircuitOpenError(RuntimeError):
    pass


class PurposeInputBudgetExceededError(ValueError):
    pass


_CIRCUITS: dict[tuple[str, str], _CircuitState] = {}


class LLMGateway:
    def __init__(self, settings: Settings, auditor: CallAuditor | None = None):
        self.settings = settings
        self.auditor = auditor
        self.last_stream_call_id: str | None = None
        self.last_stream_cost_estimate: float | None = None
        self.last_stream_provider: str | None = None
        self.last_stream_model: str | None = None
        self.adapters = {
            "openai": OpenAIAdapter(settings),
            "deepinfra": DeepInfraAdapter(settings),
        }

    async def generate(self, request: LLMRequest) -> LLMResponse:
        request = self.normalize_request(request)
        self._validate_input_budget(request)
        last_error: BaseException | None = None
        attempt_number = 0
        for candidate in self._candidates(request):
            if not self._provider_available(candidate.provider) or self._circuit_is_open(candidate):
                last_error = CircuitOpenError(
                    f"Model {candidate.provider}:{candidate.model} is unavailable"
                )
                continue

            if self.auditor is not None:
                await self.auditor.ensure_quota(self._requested_tokens(candidate))

            for local_attempt in range(1, self.settings.llm_max_attempts + 1):
                attempt_number += 1
                started = time.perf_counter()
                try:
                    async with asyncio.timeout(self.settings.llm_total_timeout_seconds):
                        response = await self.adapters[candidate.provider].generate(candidate)
                except asyncio.CancelledError as error:
                    await self._record_failed_call(
                        candidate, error, started, "cancelled", attempt_number
                    )
                    self._release_half_open(candidate)
                    raise
                except Exception as error:
                    await self._record_failed_call(
                        candidate, error, started, "failed", attempt_number
                    )
                    if not self._is_retryable(error):
                        self._record_circuit_success(candidate)
                        raise
                    last_error = error
                    if local_attempt < self.settings.llm_max_attempts:
                        await self._retry_sleep(local_attempt)
                        continue
                    self._record_circuit_failure(candidate)
                    break

                self._record_circuit_success(candidate)
                if self.auditor is None:
                    return response
                call_id, cost = await self.auditor.record_llm(
                    candidate,
                    response,
                    status="succeeded",
                    latency_ms=response.latency_ms
                    or int((time.perf_counter() - started) * 1000),
                    attempt=attempt_number,
                )
                return response.model_copy(update={"call_id": call_id, "cost_estimate": cost})

        if last_error is not None:
            raise last_error
        raise RuntimeError("No configured model is available for this request")

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        request = self.normalize_request(request)
        self._validate_input_budget(request)
        self.last_stream_call_id = None
        self.last_stream_cost_estimate = None
        self.last_stream_provider = None
        self.last_stream_model = None
        last_error: BaseException | None = None
        attempt_number = 0

        for candidate in self._candidates(request):
            if not self._provider_available(candidate.provider) or self._circuit_is_open(candidate):
                last_error = CircuitOpenError(
                    f"Model {candidate.provider}:{candidate.model} is unavailable"
                )
                continue

            if self.auditor is not None:
                await self.auditor.ensure_quota(self._requested_tokens(candidate))

            for local_attempt in range(1, self.settings.llm_max_attempts + 1):
                attempt_number += 1
                started = time.perf_counter()
                first_token_latency_ms: int | None = None
                chunks: list[str] = []
                try:
                    async with asyncio.timeout(self.settings.llm_total_timeout_seconds):
                        async for chunk in self.adapters[candidate.provider].stream(candidate):
                            if first_token_latency_ms is None:
                                first_token_latency_ms = int(
                                    (time.perf_counter() - started) * 1000
                                )
                            chunks.append(chunk)
                            yield chunk
                except asyncio.CancelledError as error:
                    await self._record_stream_call(
                        candidate, chunks, started, first_token_latency_ms,
                        "cancelled", attempt_number, error,
                    )
                    self._release_half_open(candidate)
                    raise
                except Exception as error:
                    await self._record_stream_call(
                        candidate, chunks, started, first_token_latency_ms,
                        "failed", attempt_number, error,
                    )
                    if chunks or not self._is_retryable(error):
                        if not self._is_retryable(error):
                            self._record_circuit_success(candidate)
                        else:
                            self._release_half_open(candidate)
                        raise
                    last_error = error
                    if local_attempt < self.settings.llm_max_attempts:
                        await self._retry_sleep(local_attempt)
                        continue
                    self._record_circuit_failure(candidate)
                    break

                self._record_circuit_success(candidate)
                await self._record_stream_call(
                    candidate, chunks, started, first_token_latency_ms,
                    "succeeded", attempt_number,
                )
                return

        if last_error is not None:
            raise last_error
        raise RuntimeError("No configured model is available for this request")

    async def _record_failed_call(
        self, request: LLMRequest, error: BaseException, started: float,
        status: str, attempt: int,
    ) -> None:
        if self.auditor is None:
            return
        await self.auditor.record_llm(
            request, None, status=status,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=error, attempt=attempt,
        )

    async def _record_stream_call(
        self, request: LLMRequest, chunks: list[str], started: float,
        first_token_latency_ms: int | None, status: str, attempt: int,
        error: BaseException | None = None,
    ) -> None:
        self.last_stream_provider = request.provider
        self.last_stream_model = request.model
        if self.auditor is None:
            return
        response = LLMResponse(
            provider=request.provider, model=request.model, text="".join(chunks),
            raw={"stream": True},
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        call_id, cost = await self.auditor.record_llm(
            request, response, status=status, latency_ms=response.latency_ms or 0,
            first_token_latency_ms=first_token_latency_ms, error=error, attempt=attempt,
        )
        self.last_stream_call_id = call_id
        self.last_stream_cost_estimate = cost

    def _candidates(self, request: LLMRequest) -> list[LLMRequest]:
        candidates = [request]
        fallbacks = fallback_models(request.purpose, request.model)[
            : self.settings.llm_max_fallbacks
        ]
        for option in fallbacks:
            candidates.append(
                request.model_copy(
                    update={
                        "provider": option.provider,
                        "model": option.model,
                        "max_output_tokens": min(
                            request.max_output_tokens, option.hard_max_output_tokens
                        ),
                        "reasoning_effort": option.reasoning_effort,
                    }
                )
            )
        return candidates

    @staticmethod
    def _requested_tokens(request: LLMRequest) -> int:
        from app.services.token_estimator import estimate_tokens

        return sum(estimate_tokens(message.content) for message in request.messages) + int(
            request.max_output_tokens
        )

    def _provider_available(self, provider: str) -> bool:
        adapter = self.adapters.get(provider)
        if adapter is not None and not isinstance(adapter, (OpenAIAdapter, DeepInfraAdapter)):
            return True
        if self.settings.dry_run_llm:
            return True
        if provider == "openai":
            return bool(self.settings.openai_api_key)
        if provider == "deepinfra":
            return bool(self.settings.deepinfra_api_key)
        return False

    def _circuit_is_open(self, request: LLMRequest) -> bool:
        state = _CIRCUITS.get((request.provider, request.model))
        if state is None or state.opened_until <= 0:
            return False
        if time.monotonic() >= state.opened_until:
            if state.half_open_in_flight:
                return True
            state.half_open_in_flight = True
            return False
        return True

    def _record_circuit_failure(self, request: LLMRequest) -> None:
        key = (request.provider, request.model)
        state = _CIRCUITS.setdefault(key, _CircuitState())
        state.failures += 1
        if state.failures >= self.settings.llm_circuit_failure_threshold:
            state.opened_until = time.monotonic() + self.settings.llm_circuit_cooldown_seconds
            state.half_open_in_flight = False

    @staticmethod
    def _record_circuit_success(request: LLMRequest) -> None:
        _CIRCUITS.pop((request.provider, request.model), None)

    @staticmethod
    def _release_half_open(request: LLMRequest) -> None:
        state = _CIRCUITS.get((request.provider, request.model))
        if state is not None:
            state.half_open_in_flight = False

    async def _retry_sleep(self, attempt: int) -> None:
        maximum = min(
            self.settings.llm_retry_base_seconds * (2 ** (attempt - 1)),
            self.settings.llm_retry_max_seconds,
        )
        if maximum > 0:
            await asyncio.sleep(random.uniform(maximum / 2, maximum))

    @staticmethod
    def _is_retryable(error: BaseException) -> bool:
        if isinstance(error, (asyncio.TimeoutError, APITimeoutError, APIConnectionError)):
            return True
        if isinstance(error, RateLimitError):
            return True
        if isinstance(error, APIStatusError):
            return error.status_code in {408, 409, 429} or error.status_code >= 500
        return False

    def request_for_purpose(self, purpose: StoryPurpose, messages: list) -> LLMRequest:
        option = choose_model(purpose)
        budget = purpose_budget(purpose)
        return LLMRequest(
            provider=option.provider, model=option.model, messages=messages, purpose=purpose,
            max_output_tokens=budget.default_output_tokens,
            temperature=option.temperature, top_p=option.top_p,
            reasoning_effort=option.reasoning_effort,
        )

    def normalize_request(self, request: LLMRequest) -> LLMRequest:
        option = get_model(request.model)
        budget = purpose_budget(request.purpose)
        output_limit = budget.hard_output_tokens
        if option is not None:
            output_limit = min(output_limit, option.hard_max_output_tokens)
        updates = {"max_output_tokens": min(request.max_output_tokens, output_limit)}
        if option is not None:
            updates.update(
                {
                    "temperature": request.temperature or option.temperature,
                    "top_p": request.top_p or option.top_p,
                    "reasoning_effort": request.reasoning_effort or option.reasoning_effort,
                }
            )
        return request.model_copy(update=updates)

    @staticmethod
    def _validate_input_budget(request: LLMRequest) -> None:
        from app.services.token_estimator import estimate_tokens

        estimated_input = sum(estimate_tokens(message.content) for message in request.messages)
        limit = purpose_budget(request.purpose).max_input_tokens
        if estimated_input > limit:
            raise PurposeInputBudgetExceededError(
                f"{request.purpose} input exceeds its {limit}-token budget"
            )
