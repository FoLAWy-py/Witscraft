import time
from collections.abc import AsyncIterator

import httpx
from openai import AsyncOpenAI

from app.config import Settings
from app.llm.base import LLMAdapter
from app.schemas.llm import LLMRequest, LLMResponse


class DeepInfraAdapter(LLMAdapter):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_stream_completion_status = "completed"
        self.last_stream_finish_reason: str | None = None
        self.client = (
            AsyncOpenAI(
                api_key=settings.deepinfra_api_key,
                base_url=settings.deepinfra_base_url,
                max_retries=0,
                timeout=httpx.Timeout(
                    connect=settings.llm_connect_timeout_seconds,
                    read=settings.llm_read_timeout_seconds,
                    write=settings.llm_read_timeout_seconds,
                    pool=settings.llm_connect_timeout_seconds,
                ),
            )
            if settings.deepinfra_api_key
            else None
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if self.settings.dry_run_llm or self.client is None:
            return LLMResponse(
                provider="deepinfra",
                model=request.model,
                text="林岚看见钥匙时，声音轻了下来：'你还留着它。那就说明，至少有一部分过去没有被他们改写。'",
                raw={"dry_run": True},
            )

        started = time.perf_counter()
        extra_body = dict(request.provider_options)
        if request.reasoning_effort:
            extra_body["reasoning_effort"] = request.reasoning_effort

        kwargs: dict = {
            "model": request.model,
            "messages": [self._to_chat_completion_message(message) for message in request.messages],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
        }
        if extra_body:
            kwargs["extra_body"] = extra_body
        if request.response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        response = await self.client.chat.completions.create(**kwargs)
        latency_ms = int((time.perf_counter() - started) * 1000)
        choice = response.choices[0]
        usage = response.usage
        return LLMResponse(
            provider="deepinfra",
            model=request.model,
            text=choice.message.content or "",
            raw=response.model_dump(),
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            latency_ms=latency_ms,
            completion_status=self._completion_status(getattr(choice, "finish_reason", None)),
            finish_reason=getattr(choice, "finish_reason", None),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        self.last_stream_completion_status = "interrupted"
        self.last_stream_finish_reason = None
        if self.settings.dry_run_llm or self.client is None:
            response = await self.generate(request)
            self.last_stream_completion_status = response.completion_status
            self.last_stream_finish_reason = response.finish_reason
            for chunk in response.text.split(" "):
                yield f"{chunk} "
            return

        extra_body = dict(request.provider_options)
        if request.reasoning_effort:
            extra_body["reasoning_effort"] = request.reasoning_effort

        kwargs: dict = {
            "model": request.model,
            "messages": [self._to_chat_completion_message(message) for message in request.messages],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": True,
        }
        if extra_body:
            kwargs["extra_body"] = extra_body
        if request.response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        stream = await self.client.chat.completions.create(**kwargs)
        async for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta
            finish_reason = getattr(event.choices[0], "finish_reason", None)
            if finish_reason is not None:
                self.last_stream_finish_reason = str(finish_reason)
                self.last_stream_completion_status = self._completion_status(finish_reason)
            content = getattr(delta, "content", None)
            if content:
                yield content

    @staticmethod
    def _completion_status(finish_reason) -> str:
        if finish_reason in {None, "stop", "eos", "eos_token"}:
            return "completed"
        if finish_reason in {"length", "max_tokens", "max_output_tokens"}:
            return "length_limited"
        if finish_reason in {"content_filter", "error"}:
            return "failed"
        return "interrupted"

    @staticmethod
    def _to_chat_completion_message(message) -> dict[str, str]:
        role = "system" if message.role == "developer" else message.role
        return {"role": role, "content": message.content}
