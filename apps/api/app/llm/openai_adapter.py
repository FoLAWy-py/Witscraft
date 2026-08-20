import time
from collections.abc import AsyncIterator

import httpx
from openai import AsyncOpenAI

from app.config import Settings
from app.llm.base import LLMAdapter
from app.schemas.llm import LLMRequest, LLMResponse


class OpenAIAdapter(LLMAdapter):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = (
            AsyncOpenAI(
                api_key=settings.openai_api_key,
                max_retries=0,
                timeout=httpx.Timeout(
                    connect=settings.llm_connect_timeout_seconds,
                    read=settings.llm_read_timeout_seconds,
                    write=settings.llm_read_timeout_seconds,
                    pool=settings.llm_connect_timeout_seconds,
                ),
            )
            if settings.openai_api_key
            else None
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if self.settings.dry_run_llm or self.client is None:
            return LLMResponse(
                provider="openai",
                model=request.model,
                text="夜色压低了档案室的灯光。她没有立刻回答，只把那枚钥匙推回你的掌心，像是在确认你是否仍愿意相信她。",
                raw={"dry_run": True},
            )

        started = time.perf_counter()
        instructions, input_messages = self._split_instructions(request)
        input_messages = self._json_input_messages(
            request,
            input_messages,
        )
        kwargs: dict = {
            "model": request.model,
            "input": input_messages,
            "max_output_tokens": request.max_output_tokens,
        }
        if not request.reasoning_effort:
            kwargs["temperature"] = request.temperature
            kwargs["top_p"] = request.top_p
        if instructions:
            kwargs["instructions"] = instructions
        if request.reasoning_effort:
            kwargs["reasoning"] = {"effort": request.reasoning_effort}
        if request.response_format == "json":
            kwargs["text"] = {"format": {"type": "json_object"}}

        response = await self.client.responses.create(**kwargs)
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = getattr(response, "usage", None)
        return LLMResponse(
            provider="openai",
            model=request.model,
            text=response.output_text,
            raw=response.model_dump(),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            latency_ms=latency_ms,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        if self.settings.dry_run_llm or self.client is None:
            response = await self.generate(request)
            if response.text:
                yield response.text
            return

        instructions, input_messages = self._split_instructions(request)
        input_messages = self._json_input_messages(
            request,
            input_messages,
        )
        kwargs: dict = {
            "model": request.model,
            "input": input_messages,
            "max_output_tokens": request.max_output_tokens,
            "stream": True,
        }
        if not request.reasoning_effort:
            kwargs["temperature"] = request.temperature
            kwargs["top_p"] = request.top_p
        if instructions:
            kwargs["instructions"] = instructions
        if request.reasoning_effort:
            kwargs["reasoning"] = {"effort": request.reasoning_effort}
        if request.response_format == "json":
            kwargs["text"] = {"format": {"type": "json_object"}}

        stream = await self.client.responses.create(**kwargs)
        async for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta

    @staticmethod
    def _split_instructions(request: LLMRequest) -> tuple[str | None, list[dict[str, str]]]:
        instruction_parts: list[str] = []
        input_messages: list[dict[str, str]] = []

        for message in request.messages:
            if message.role in {"system", "developer"}:
                instruction_parts.append(message.content)
            else:
                input_messages.append({"role": message.role, "content": message.content})

        instructions = "\n\n".join(instruction_parts) if instruction_parts else None
        return instructions, input_messages

    @staticmethod
    def _json_input_messages(
        request: LLMRequest,
        input_messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        if request.response_format != "json":
            return input_messages

        if any("json" in message["content"] for message in input_messages):
            return input_messages

        return [
            *input_messages,
            {"role": "user", "content": "Return one valid json object."},
        ]
