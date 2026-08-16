import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.db.models import GenerationRequest
from app.routers.chat import _with_idempotency_header
from app.schemas.chat import ChatRequest, ChatResponse, StoryState
from app.services.story_engine import StoryEngine


class CommitTrackingSession:
    def __init__(self):
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class TransactionCheckingEmbeddings:
    def __init__(self, session: CommitTrackingSession):
        self.session = session
        self.calls = 0

    async def embed_many(self, texts: list[str], *, purpose: str) -> list[list[float]]:
        assert self.session.commits == 1
        assert purpose == "embedding_memory"
        self.calls += 1
        return [[float(index)] for index, _ in enumerate(texts)]


def _request(**updates) -> ChatRequest:
    values = {
        "message": "打开那扇门",
        "story_id": str(uuid4()),
        "branch_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "branch_version": 3,
    }
    values.update(updates)
    return ChatRequest(**values)


def _response(key: str) -> ChatResponse:
    return ChatResponse(
        message_id=str(uuid4()),
        content="门开了。",
        story_state=StoryState(),
        retrieved_memories=[],
        canon_facts=[],
        model_call={},
        idempotency_key=key,
        branch_version=4,
    )


def test_request_hash_ignores_idempotency_key_but_not_payload() -> None:
    first = _request(idempotency_key="request-key-one")
    same_payload = first.model_copy(update={"idempotency_key": "request-key-two"})
    changed_payload = first.model_copy(update={"message": "离开这里"})

    assert StoryEngine._generation_request_hash(first) == StoryEngine._generation_request_hash(
        same_payload
    )
    assert StoryEngine._generation_request_hash(first) != StoryEngine._generation_request_hash(
        changed_payload
    )


def test_completed_generation_replays_serialized_response() -> None:
    request = _request()
    request_hash = StoryEngine._generation_request_hash(request)
    generation = GenerationRequest(
        user_id=uuid4(),
        story_id=uuid4(),
        branch_id=uuid4(),
        idempotency_key=request.idempotency_key,
        request_hash=request_hash,
        status="completed",
        expected_branch_version=3,
        response=_response(request.idempotency_key).model_dump(mode="json"),
    )
    engine = object.__new__(StoryEngine)

    _, replay = engine._resolve_existing_generation(generation, request_hash)

    assert replay is not None
    assert replay.content == "门开了。"
    assert replay.branch_version == 4


@pytest.mark.parametrize("status", ["processing", "failed", "cancelled"])
def test_unfinished_generation_cannot_charge_again_with_same_key(status: str) -> None:
    request = _request()
    request_hash = StoryEngine._generation_request_hash(request)
    generation = GenerationRequest(
        user_id=uuid4(),
        story_id=uuid4(),
        branch_id=uuid4(),
        idempotency_key=request.idempotency_key,
        request_hash=request_hash,
        status=status,
        expected_branch_version=3,
    )
    engine = object.__new__(StoryEngine)

    with pytest.raises(HTTPException) as caught:
        engine._resolve_existing_generation(generation, request_hash)

    assert caught.value.status_code == 409


def test_reusing_key_with_different_payload_is_rejected() -> None:
    generation = GenerationRequest(
        user_id=uuid4(),
        story_id=uuid4(),
        branch_id=uuid4(),
        idempotency_key="request-key",
        request_hash="original",
        status="completed",
        expected_branch_version=0,
        response={},
    )
    engine = object.__new__(StoryEngine)

    with pytest.raises(HTTPException, match="different request") as caught:
        engine._resolve_existing_generation(generation, "changed")

    assert caught.value.status_code == 409


def test_stream_checkpoint_uses_time_or_character_threshold() -> None:
    check = StoryEngine._should_checkpoint_stream

    assert check(
        has_checkpoint=False,
        current_characters=1,
        checkpoint_characters=0,
        now=0.1,
        checkpoint_at=0,
        character_threshold=512,
        time_threshold=1,
    )
    assert not check(
        has_checkpoint=True,
        current_characters=511,
        checkpoint_characters=0,
        now=0.9,
        checkpoint_at=0,
        character_threshold=512,
        time_threshold=1,
    )
    assert check(
        has_checkpoint=True,
        current_characters=512,
        checkpoint_characters=0,
        now=0.1,
        checkpoint_at=0,
        character_threshold=512,
        time_threshold=1,
    )
    assert check(
        has_checkpoint=True,
        current_characters=10,
        checkpoint_characters=0,
        now=1,
        checkpoint_at=0,
        character_threshold=512,
        time_threshold=1,
    )


def test_idempotency_header_populates_request_body() -> None:
    payload = _request(idempotency_key=None)
    request = Request(
        {"type": "http", "headers": [(b"idempotency-key", b"header-request-key")]}
    )

    merged = _with_idempotency_header(payload, request)

    assert merged.idempotency_key == "header-request-key"


def test_conflicting_idempotency_header_and_body_is_rejected() -> None:
    payload = _request(idempotency_key="body-request-key")
    request = Request(
        {"type": "http", "headers": [(b"idempotency-key", b"header-request-key")]}
    )

    with pytest.raises(HTTPException) as caught:
        _with_idempotency_header(payload, request)

    assert caught.value.status_code == 409


def test_embedding_runs_after_knowledge_read_transaction_is_released() -> None:
    engine = object.__new__(StoryEngine)
    session = CommitTrackingSession()
    embeddings = TransactionCheckingEmbeddings(session)
    engine.session = session
    engine.embedding_service = embeddings

    async def memory_exists(_story_id, _branch_id, content: str) -> bool:
        return content == "already known"

    async def fact_exists(_story_id, _branch_id, content: str) -> bool:
        return content == "known fact"

    engine._memory_exists = memory_exists
    engine._canon_fact_exists = fact_exists

    prepared_memories, prepared_facts = asyncio.run(
        engine._prepare_extracted_knowledge(
            SimpleNamespace(id=uuid4()),
            SimpleNamespace(id=uuid4()),
            ["already known", "new memory", "new memory"],
            ["known fact", "new fact", "new fact"],
        )
    )

    assert prepared_memories == [("new memory", [0.0])]
    assert prepared_facts == ["new fact"]
    assert embeddings.calls == 1
