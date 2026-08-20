import asyncio
from types import SimpleNamespace

from app.schemas.chat import ChatRequest
from app.schemas.llm import ChatMessage, LLMRequest, LLMResponse
from app.services.story_engine import StoryEngine


class FakeGateway:
    def __init__(
        self, text: str = "扩" * 450, *, texts: list[str] | None = None, fail: bool = False
    ) -> None:
        self.texts = list(texts or [text])
        self.fail = fail
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("provider unavailable")
        return LLMResponse(
            provider=request.provider,
            model=request.model,
            text=self.texts[min(len(self.requests) - 1, len(self.texts) - 1)],
        )


def _engine(gateway: FakeGateway) -> StoryEngine:
    engine = StoryEngine.__new__(StoryEngine)
    engine.llm_gateway = gateway
    return engine


def _request() -> LLMRequest:
    return LLMRequest(
        provider="deepinfra",
        model="Qwen/Qwen3-Max",
        messages=[ChatMessage(role="user", content="我检查信封。")],
    )


def test_short_chapter_gets_one_bounded_replacement_call() -> None:
    gateway = FakeGateway()
    content, response = asyncio.run(
        _engine(gateway)._expand_short_chapter(
            "短稿",
            story=SimpleNamespace(target_chapter_length=500, chapter_length_unit="characters"),
            request=ChatRequest(message="我检查信封。", story_id="story"),
            chapter=SimpleNamespace(),
            llm_request=_request(),
        )
    )

    assert content == "扩" * 450
    assert response is not None
    assert len(gateway.requests) == 1
    assert gateway.requests[0].stream is False
    assert "measures only 2" in gateway.requests[0].messages[-1].content
    assert "no chapter heading" in gateway.requests[0].messages[-1].content


def test_acceptable_chapter_skips_replacement_call() -> None:
    gateway = FakeGateway()
    original = "足" * 425
    content, response = asyncio.run(
        _engine(gateway)._expand_short_chapter(
            original,
            story=SimpleNamespace(target_chapter_length=500, chapter_length_unit="characters"),
            request=ChatRequest(message="继续观察。", story_id="story"),
            chapter=SimpleNamespace(),
            llm_request=_request(),
        )
    )

    assert content == original
    assert response is None
    assert gateway.requests == []


def test_first_improvement_below_floor_gets_one_final_bounded_attempt() -> None:
    gateway = FakeGateway(texts=["改" * 300, "扩" * 450])
    content, response = asyncio.run(
        _engine(gateway)._expand_short_chapter(
            "短稿",
            story=SimpleNamespace(target_chapter_length=500, chapter_length_unit="characters"),
            request=ChatRequest(message="继续观察。", story_id="story"),
            chapter=SimpleNamespace(),
            llm_request=_request(),
        )
    )

    assert content == "扩" * 450
    assert response is not None
    assert len(gateway.requests) == 2
    assert "measures only 300" in gateway.requests[1].messages[-1].content
    assert "hard minimum of 425" in gateway.requests[1].messages[-1].content


def test_failed_replacement_keeps_the_successful_primary_draft() -> None:
    gateway = FakeGateway(fail=True)
    content, response = asyncio.run(
        _engine(gateway)._expand_short_chapter(
            "短稿",
            story=SimpleNamespace(target_chapter_length=500, chapter_length_unit="characters"),
            request=ChatRequest(message="继续观察。", story_id="story"),
            chapter=SimpleNamespace(),
            llm_request=_request(),
        )
    )

    assert content == "短稿"
    assert response is None
    assert len(gateway.requests) == 1
