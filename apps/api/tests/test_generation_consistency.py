import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.db.models import GenerationRequest
from app.routers.chat import _with_idempotency_header
from app.schemas.chat import ChatRequest, ChatResponse, StoryState
from app.services.embeddings import EmbeddingMetadata, embedding_content_hash
from app.services.story_engine import PreparedMemory, StoryEngine


class CommitTrackingSession:
    def __init__(self):
        self.commits = 0
        self.added = []

    async def commit(self) -> None:
        self.commits += 1

    def add(self, value) -> None:
        self.added.append(value)


class TransactionCheckingEmbeddings:
    def __init__(self, session: CommitTrackingSession):
        self.session = session
        self.calls = 0

    async def embed_many(self, texts: list[str], *, purpose: str) -> list[list[float]]:
        assert self.session.commits == 1
        assert purpose == "embedding_memory"
        self.calls += 1
        return [[float(index)] for index, _ in enumerate(texts)]

    def metadata(self, text: str, vector: list[float]) -> EmbeddingMetadata:
        return EmbeddingMetadata(
            model="local:test-embedding",
            dimensions=len(vector),
            version="test-v1",
            content_hash=embedding_content_hash(text),
            embedded_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
        )


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

    async def recent_memories(_story_id, _branch_id):
        return []

    engine._memory_exists = memory_exists
    engine._canon_fact_exists = fact_exists
    engine._load_recent_memory_candidates = recent_memories

    prepared_memories, prepared_facts = asyncio.run(
        engine._prepare_extracted_knowledge(
            SimpleNamespace(id=uuid4()),
            SimpleNamespace(id=uuid4()),
            [
                "already known",
                "Mira discovers the sealed archive and obtains its key.",
                "Mira discovers the sealed archive and obtains its key.",
            ],
            ["known fact", "new fact", "new fact"],
            entity_names=["Mira", "sealed archive"],
        )
    )

    assert len(prepared_memories) == 1
    assert prepared_memories[0].content == "Mira discovers the sealed archive and obtains its key"
    assert prepared_memories[0].importance == 7
    assert prepared_memories[0].entity_tags == ("Mira", "sealed archive")
    assert prepared_memories[0].embedding == [0.0]
    assert prepared_memories[0].embedding_model == "local:test-embedding"
    assert prepared_memories[0].embedding_dimensions == 1
    assert prepared_memories[0].embedding_version == "test-v1"
    assert prepared_facts == ["new fact"]
    assert embeddings.calls == 1


def test_low_value_and_near_duplicate_memories_skip_embedding() -> None:
    engine = object.__new__(StoryEngine)
    session = CommitTrackingSession()
    embeddings = TransactionCheckingEmbeddings(session)
    engine.session = session
    engine.embedding_service = embeddings

    async def memory_exists(_story_id, _branch_id, _content: str) -> bool:
        return False

    async def fact_exists(_story_id, _branch_id, _content: str) -> bool:
        return False

    existing = SimpleNamespace(
        content="Mira discovers the sealed archive and obtains its key.",
        importance=3,
        recency_score=0.2,
        entity_tags=["Mira"],
        embedding=[0.75],
    )

    async def recent_memories(_story_id, _branch_id):
        return [existing]

    engine._memory_exists = memory_exists
    engine._canon_fact_exists = fact_exists
    engine._load_recent_memory_candidates = recent_memories

    prepared_memories, _ = asyncio.run(
        engine._prepare_extracted_knowledge(
            SimpleNamespace(id=uuid4()),
            SimpleNamespace(id=uuid4()),
            [
                "Mira nods quietly.",
                "Mira discovers the sealed archive, and obtains its key!",
            ],
            [],
            entity_names=["Mira", "sealed archive"],
        )
    )

    assert prepared_memories == []
    assert embeddings.calls == 0
    assert existing.importance == 7
    assert existing.entity_tags == ["Mira", "sealed archive"]
    assert existing.recency_score == 1.0
    assert existing.embedding == [0.75]


def test_near_duplicate_filter_preserves_similar_events_for_different_entities() -> None:
    engine = object.__new__(StoryEngine)
    session = CommitTrackingSession()
    embeddings = TransactionCheckingEmbeddings(session)
    engine.session = session
    engine.embedding_service = embeddings

    async def never_exists(_story_id, _branch_id, _content: str) -> bool:
        return False

    async def recent_memories(_story_id, _branch_id):
        return [
            SimpleNamespace(
                content="Mira discovers the sealed archive and obtains its key.",
                entity_tags=["Mira"],
            )
        ]

    engine._memory_exists = never_exists
    engine._canon_fact_exists = never_exists
    engine._load_recent_memory_candidates = recent_memories

    prepared_memories, _ = asyncio.run(
        engine._prepare_extracted_knowledge(
            SimpleNamespace(id=uuid4()),
            SimpleNamespace(id=uuid4()),
            ["Lena discovers the sealed archive and obtains its key."],
            [],
            entity_names=["Mira", "Lena"],
        )
    )

    assert [memory.content for memory in prepared_memories] == [
        "Lena discovers the sealed archive and obtains its key"
    ]
    assert prepared_memories[0].entity_tags == ("Lena",)
    assert embeddings.calls == 1


def test_prepared_memory_quality_metadata_is_persisted() -> None:
    engine = object.__new__(StoryEngine)
    session = CommitTrackingSession()
    engine.session = session
    story = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        main_character_id=uuid4(),
    )
    branch = SimpleNamespace(id=uuid4())
    prepared = PreparedMemory(
        content="Mira discovers the sealed archive",
        importance=7,
        entity_tags=("Mira", "sealed archive"),
        embedding=[0.25, 0.75],
        embedding_model="local:test-embedding",
        embedding_dimensions=2,
        embedding_version="test-v1",
        content_hash=embedding_content_hash("Mira discovers the sealed archive"),
        embedded_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )

    added = engine._add_prepared_memories(
        story,
        branch,
        uuid4(),
        [prepared],
        "llm",
    )

    assert added == [prepared.content]
    assert len(session.added) == 1
    row = session.added[0]
    assert row.importance == 7
    assert row.entity_tags == ["Mira", "sealed archive"]
    assert row.embedding == [0.25, 0.75]
    assert row.embedding_model == "local:test-embedding"
    assert row.embedding_dimensions == 2
    assert row.embedding_version == "test-v1"
    assert row.content_hash == prepared.content_hash
