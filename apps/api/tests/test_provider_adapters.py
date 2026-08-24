import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.llm import deepinfra_adapter as deepinfra_module
from app.llm import openai_adapter as openai_module
from app.llm.deepinfra_adapter import DeepInfraAdapter
from app.llm.openai_adapter import OpenAIAdapter
from app.schemas.llm import ChatMessage, LLMRequest


class AsyncCreate:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class AsyncEvents:
    def __init__(self, events):
        self.events = events

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self.events:
            yield event


def _request(**updates) -> LLMRequest:
    values = {
        "provider": "openai",
        "model": "test-model",
        "purpose": "state_update",
        "messages": [
            ChatMessage(role="system", content="system rules"),
            ChatMessage(role="developer", content="developer context"),
            ChatMessage(role="user", content="user input"),
        ],
        "max_output_tokens": 512,
        "temperature": 0.4,
        "top_p": 0.8,
        "reasoning_effort": "medium",
        "response_format": "json",
        "provider_options": {"custom_flag": True},
    }
    values.update(updates)
    return LLMRequest(**values)


def test_adapters_disable_sdk_retries_and_apply_split_timeouts(monkeypatch) -> None:
    captured: list[dict] = []

    def fake_client(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(openai_module, "AsyncOpenAI", fake_client)
    monkeypatch.setattr(deepinfra_module, "AsyncOpenAI", fake_client)
    settings = Settings(
        openai_api_key="openai-test",
        deepinfra_api_key="deepinfra-test",
        llm_connect_timeout_seconds=3,
        llm_read_timeout_seconds=17,
    )

    OpenAIAdapter(settings)
    DeepInfraAdapter(settings)

    assert len(captured) == 2
    assert all(call["max_retries"] == 0 for call in captured)
    assert all(call["timeout"].connect == 3 for call in captured)
    assert all(call["timeout"].read == 17 for call in captured)
    assert all(call["timeout"].write == 17 for call in captured)
    assert all(call["timeout"].pool == 3 for call in captured)
    assert "base_url" not in captured[0]
    assert captured[1]["base_url"] == settings.deepinfra_base_url


def test_openai_generate_maps_responses_request_and_usage() -> None:
    raw = {"id": "response-1"}
    create = AsyncCreate(
        SimpleNamespace(
            output_text='{"state":"updated"}',
            usage=SimpleNamespace(input_tokens=31, output_tokens=12),
            model_dump=lambda: raw,
        )
    )
    adapter = OpenAIAdapter(Settings(openai_api_key="test-key"))
    adapter.client = SimpleNamespace(responses=create)

    response = asyncio.run(adapter.generate(_request()))

    call = create.calls[0]
    assert call["instructions"] == "system rules\n\ndeveloper context"
    assert call["input"] == [
        {"role": "user", "content": "user input"},
        {"role": "user", "content": "Return one valid json object."},
    ]
    assert call["max_output_tokens"] == 512
    assert call["reasoning"] == {"effort": "medium"}
    assert call["text"] == {"format": {"type": "json_object"}}
    assert "temperature" not in call
    assert "top_p" not in call
    assert response.text == '{"state":"updated"}'
    assert response.input_tokens == 31
    assert response.output_tokens == 12
    assert response.raw == raw


def test_openai_non_reasoning_request_preserves_sampling_parameters() -> None:
    create = AsyncCreate(
        SimpleNamespace(
            output_text="ok",
            usage=None,
            model_dump=lambda: {},
        )
    )
    adapter = OpenAIAdapter(Settings(openai_api_key="test-key"))
    adapter.client = SimpleNamespace(responses=create)

    asyncio.run(adapter.generate(_request(reasoning_effort=None, response_format="text")))

    assert create.calls[0]["temperature"] == 0.4
    assert create.calls[0]["top_p"] == 0.8
    assert "reasoning" not in create.calls[0]
    assert "text" not in create.calls[0]


def test_openai_incomplete_max_output_maps_to_length_limited() -> None:
    create = AsyncCreate(
        SimpleNamespace(
            output_text="unfinished",
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            usage=None,
            model_dump=lambda: {},
        )
    )
    adapter = OpenAIAdapter(Settings(openai_api_key="test-key"))
    adapter.client = SimpleNamespace(responses=create)

    response = asyncio.run(adapter.generate(_request(response_format="text")))

    assert response.completion_status == "length_limited"
    assert response.finish_reason == "max_output_tokens"


def test_openai_stream_yields_only_text_delta_events() -> None:
    events = AsyncEvents(
        [
            SimpleNamespace(type="response.created"),
            SimpleNamespace(type="response.output_text.delta", delta="first"),
            SimpleNamespace(type="response.output_text.delta", delta=" second"),
            SimpleNamespace(type="response.completed"),
        ]
    )
    create = AsyncCreate(events)
    adapter = OpenAIAdapter(Settings(openai_api_key="test-key"))
    adapter.client = SimpleNamespace(responses=create)

    async def collect() -> list[str]:
        return [chunk async for chunk in adapter.stream(_request())]

    assert asyncio.run(collect()) == ["first", " second"]
    assert create.calls[0]["stream"] is True
    assert create.calls[0]["input"][-1] == {
        "role": "user",
        "content": "Return one valid json object.",
    }


def test_openai_json_request_preserves_existing_lowercase_instruction() -> None:
    create = AsyncCreate(
        SimpleNamespace(
            output_text='{"ok":true}',
            usage=None,
            model_dump=lambda: {},
        )
    )
    adapter = OpenAIAdapter(Settings(openai_api_key="test-key"))
    adapter.client = SimpleNamespace(responses=create)
    request = _request(
        messages=[
            ChatMessage(role="system", content="Return a valid json object."),
            ChatMessage(role="user", content="Evaluate this response."),
        ]
    )

    asyncio.run(adapter.generate(request))

    assert create.calls[0]["instructions"] == "Return a valid json object."
    assert create.calls[0]["input"][-1] == {
        "role": "user",
        "content": "Return one valid json object.",
    }


def test_openai_json_request_preserves_existing_lowercase_user_input() -> None:
    create = AsyncCreate(
        SimpleNamespace(
            output_text='{"ok":true}',
            usage=None,
            model_dump=lambda: {},
        )
    )
    adapter = OpenAIAdapter(Settings(openai_api_key="test-key"))
    adapter.client = SimpleNamespace(responses=create)
    request = _request(
        messages=[
            ChatMessage(role="system", content="Return an object."),
            ChatMessage(role="user", content="Return this as json."),
        ]
    )

    asyncio.run(adapter.generate(request))

    assert create.calls[0]["input"] == [{"role": "user", "content": "Return this as json."}]


def test_deepinfra_generate_maps_chat_request_and_usage() -> None:
    raw = {"id": "chat-1"}
    response_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"event":"saved"}'))],
        usage=SimpleNamespace(prompt_tokens=22, completion_tokens=9),
        model_dump=lambda: raw,
    )
    create = AsyncCreate(response_value)
    adapter = DeepInfraAdapter(Settings(deepinfra_api_key="test-key"))
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=create))
    request = _request(provider="deepinfra")

    response = asyncio.run(adapter.generate(request))

    call = create.calls[0]
    assert call["messages"] == [
        {"role": "system", "content": "system rules"},
        {"role": "system", "content": "developer context"},
        {"role": "user", "content": "user input"},
    ]
    assert call["max_tokens"] == 512
    assert call["extra_body"] == {
        "custom_flag": True,
        "reasoning_effort": "medium",
    }
    assert call["response_format"] == {"type": "json_object"}
    assert response.text == '{"event":"saved"}'
    assert response.input_tokens == 22
    assert response.output_tokens == 9
    assert response.raw == raw


def test_deepinfra_stream_filters_empty_choices_and_content() -> None:
    stream = AsyncEvents(
        [
            SimpleNamespace(choices=[]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="alpha"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=" beta"))]),
        ]
    )
    create = AsyncCreate(stream)
    adapter = DeepInfraAdapter(Settings(deepinfra_api_key="test-key"))
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=create))

    async def collect() -> list[str]:
        return [chunk async for chunk in adapter.stream(_request(provider="deepinfra"))]

    assert asyncio.run(collect()) == ["alpha", " beta"]
    assert create.calls[0]["stream"] is True


def test_deepinfra_length_finish_reason_is_preserved() -> None:
    response_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="unfinished"), finish_reason="length"
            )
        ],
        usage=SimpleNamespace(prompt_tokens=22, completion_tokens=512),
        model_dump=lambda: {},
    )
    create = AsyncCreate(response_value)
    adapter = DeepInfraAdapter(Settings(deepinfra_api_key="test-key"))
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=create))

    response = asyncio.run(adapter.generate(_request(provider="deepinfra")))

    assert response.completion_status == "length_limited"
    assert response.finish_reason == "length"


@pytest.mark.parametrize("adapter_type", [OpenAIAdapter, DeepInfraAdapter])
def test_provider_errors_propagate_without_adapter_retry(adapter_type) -> None:
    error = httpx.ReadTimeout("provider timed out")
    create = AsyncCreate(error=error)
    settings = Settings(openai_api_key="test-key", deepinfra_api_key="test-key")
    adapter = adapter_type(settings)
    if isinstance(adapter, OpenAIAdapter):
        adapter.client = SimpleNamespace(responses=create)
        request = _request()
    else:
        adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=create))
        request = _request(provider="deepinfra")

    with pytest.raises(httpx.ReadTimeout, match="provider timed out"):
        asyncio.run(adapter.generate(request))

    assert len(create.calls) == 1
