import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import Settings
from app.embedding_config import EMBEDDING_VECTOR_DIMENSIONS, LOCAL_EMBEDDING_MODEL
from app.services.embeddings import (
    EmbeddingService,
    cosine_similarity,
    embedding_content_hash,
    embedding_storage_values,
    stored_embedding,
)
from app.services.story_engine import MEMORY_VECTOR_SEARCH_MIN_ITEMS, StoryEngine
from app.services.turn_context import TurnContext


class FakeScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return FakeScalarResult(self.values)

    def scalar_one_or_none(self):
        return self.values[0] if self.values else None


class FakeSession:
    def __init__(self, memories):
        self.memories = memories
        self.execute_calls = 0

    async def execute(self, _query):
        self.execute_calls += 1
        return FakeResult(self.memories)


class CountingEmbeddingService:
    def __init__(self, vector=None, threshold=MEMORY_VECTOR_SEARCH_MIN_ITEMS):
        self.vector = vector or [0.0, 1.0]
        self.calls = 0
        self.cache_hits = 0
        self.settings = SimpleNamespace(memory_vector_search_min_items=threshold)

    async def embed(self, _text, **_kwargs):
        self.calls += 1
        return self.vector

    async def record_cache_hit(self, _text, _vector, **_kwargs):
        self.cache_hits += 1

    @staticmethod
    def is_compatible(*, model, dimensions, version, vector):
        return model == "local:test-embedding" and dimensions == len(vector) and version == "test-v1"

    @staticmethod
    def is_model_version_compatible(*, model, dimensions, version):
        return (
            model == "local:test-embedding"
            and dimensions == 2
            and version == "test-v1"
        )


class FakeEmbeddingClient:
    def __init__(self, dimensions: int):
        self.embeddings = self
        self.dimensions = dimensions
        self.request = None

    async def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=[0.0] * self.dimensions)],
            usage=SimpleNamespace(prompt_tokens=3),
        )


def _engine(memories, *, threshold=MEMORY_VECTOR_SEARCH_MIN_ITEMS) -> tuple[StoryEngine, CountingEmbeddingService]:
    engine = StoryEngine.__new__(StoryEngine)
    engine.session = FakeSession(memories)
    embedding_service = CountingEmbeddingService(threshold=threshold)
    engine.embedding_service = embedding_service
    engine.turn_context = TurnContext()
    return engine, embedding_service


def _memory(index: int, embedding=None):
    return SimpleNamespace(
        content=f"memory-{index}",
        importance=5,
        recency_score=1,
        entity_tags=[],
        embedding=embedding,
        embedding_model="local:test-embedding",
        embedding_dimensions=len(embedding or []),
        embedding_version="test-v1",
    )


def test_empty_memory_set_skips_query_embedding() -> None:
    engine, embedding_service = _engine([])

    result = asyncio.run(engine._load_memories(uuid4(), uuid4(), "寻找钥匙"))

    assert result == []
    assert embedding_service.calls == 0


def test_small_memory_set_uses_structured_order_without_embedding() -> None:
    memories = [_memory(index) for index in range(12)]
    engine, embedding_service = _engine(memories)

    result = asyncio.run(engine._load_memories(uuid4(), uuid4(), "寻找钥匙"))

    assert result == [f"memory-{index}" for index in range(8)]
    assert embedding_service.calls == 0


def test_small_memory_set_uses_keyword_and_entity_hybrid_ranking_without_embedding() -> None:
    memories = [_memory(index) for index in range(12)]
    memories[0].importance = 10
    memories[-1].content = "林岚把旧钥匙藏进钟楼暗格"
    memories[-1].importance = 2
    memories[-1].entity_tags = ["林岚", "旧钥匙", "钟楼"]
    engine, embedding_service = _engine(memories)

    result = asyncio.run(engine._load_memories(uuid4(), uuid4(), "寻找旧钥匙"))

    assert result[0] == "林岚把旧钥匙藏进钟楼暗格"
    assert embedding_service.calls == 0


def test_hybrid_ranking_uses_relative_update_recency() -> None:
    memories = [_memory(0), _memory(1)]
    memories[0].updated_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    memories[1].updated_at = memories[0].updated_at + timedelta(days=10)
    engine, embedding_service = _engine(memories)

    result = asyncio.run(engine._load_memories(uuid4(), uuid4(), "没有词汇命中"))

    assert result[0] == "memory-1"
    assert embedding_service.calls == 0


def test_state_and_relationships_share_one_snapshot_read() -> None:
    snapshot = SimpleNamespace(
        state={
            "location": "钟楼",
            "time": "午夜",
            "relationships": [{"name": "林岚", "status": "ally"}],
        }
    )
    engine, _embedding_service = _engine([snapshot])
    story_id = uuid4()
    branch_id = uuid4()

    state = asyncio.run(engine._load_state(story_id, branch_id))
    relationships = asyncio.run(engine._load_relationships(story_id, branch_id))

    assert state.location == "钟楼"
    assert state.time == "午夜"
    assert relationships == [{"name": "林岚", "status": "ally"}]
    assert engine.session.execute_calls == 1


def test_large_memory_set_reuses_query_embedding_and_ranks_semantically() -> None:
    memories = [
        _memory(index, [1.0, 0.0])
        for index in range(MEMORY_VECTOR_SEARCH_MIN_ITEMS + 1)
    ]
    memories[-1].embedding = [0.0, 1.0]
    engine, embedding_service = _engine(memories)
    story_id = uuid4()
    branch_id = uuid4()

    first = asyncio.run(engine._load_memories(story_id, branch_id, "寻找钥匙"))
    second = asyncio.run(engine._load_memories(story_id, branch_id, "寻找钥匙"))

    assert first[0] == f"memory-{MEMORY_VECTOR_SEARCH_MIN_ITEMS}"
    assert second == first
    assert embedding_service.calls == 1
    assert embedding_service.cache_hits == 0
    assert engine.session.execute_calls == 1


def test_incompatible_embedding_version_is_not_compared_semantically() -> None:
    memories = [
        _memory(index, [1.0, 0.0])
        for index in range(MEMORY_VECTOR_SEARCH_MIN_ITEMS + 1)
    ]
    memories[-1].embedding = [0.0, 1.0]
    memories[-1].embedding_version = "legacy-v0"
    engine, _embedding_service = _engine(memories)

    result = asyncio.run(engine._load_memories(uuid4(), uuid4(), "寻找钥匙"))

    assert result[0] == "memory-0"
    assert memories[-1].content not in result


def test_all_legacy_vectors_use_hybrid_ranking_and_skip_query_embedding() -> None:
    memories = [
        _memory(index, [1.0, 0.0])
        for index in range(MEMORY_VECTOR_SEARCH_MIN_ITEMS + 1)
    ]
    for memory in memories:
        memory.embedding_model = "legacy:unversioned"
        memory.embedding_version = "legacy-v0"
    memories[-1].content = "韩医生把旧钥匙锁进档案室"
    memories[-1].entity_tags = ["韩医生", "旧钥匙", "档案室"]
    engine, embedding_service = _engine(memories)

    result = asyncio.run(engine._load_memories(uuid4(), uuid4(), "旧钥匙在哪里"))

    assert result[0] == "韩医生把旧钥匙锁进档案室"
    assert embedding_service.calls == 0


def test_wrong_dimension_metadata_skips_unusable_query_embedding() -> None:
    memories = [
        _memory(index, [1.0, 0.0])
        for index in range(MEMORY_VECTOR_SEARCH_MIN_ITEMS + 1)
    ]
    for memory in memories:
        memory.embedding_dimensions = 1
    engine, embedding_service = _engine(memories)

    asyncio.run(engine._load_memories(uuid4(), uuid4(), "寻找钥匙"))

    assert embedding_service.calls == 0


def test_configured_threshold_controls_semantic_embedding_activation() -> None:
    memories = [_memory(index, [1.0, 0.0]) for index in range(3)]
    memories[-1].embedding = [0.0, 1.0]
    engine, embedding_service = _engine(memories, threshold=2)

    result = asyncio.run(engine._load_memories(uuid4(), uuid4(), "寻找钥匙"))

    assert result[0] == "memory-2"
    assert embedding_service.calls == 1


def test_query_embedding_cache_records_direct_reuse() -> None:
    engine, embedding_service = _engine([])

    first = asyncio.run(engine._embed_query_once("寻找钥匙"))
    second = asyncio.run(engine._embed_query_once("寻找钥匙"))

    assert second == first
    assert embedding_service.calls == 1
    assert embedding_service.cache_hits == 1


def test_embedding_batch_uses_one_deterministic_pass_in_dry_run() -> None:
    service = EmbeddingService(Settings(dry_run_llm=True))

    vectors = asyncio.run(service.embed_many(["第一条记忆", "第二条记忆"]))

    assert len(vectors) == 2
    assert all(len(vector) == EMBEDDING_VECTOR_DIMENSIONS for vector in vectors)


def test_embedding_metadata_binds_content_model_dimensions_and_version() -> None:
    service = EmbeddingService(Settings(dry_run_llm=True, embedding_version="test-v2"))
    vector = asyncio.run(service.embed("  林岚   找到钥匙  "))

    metadata = service.metadata("  林岚   找到钥匙  ", vector)

    assert metadata.model == f"local:{LOCAL_EMBEDDING_MODEL}"
    assert metadata.dimensions == EMBEDDING_VECTOR_DIMENSIONS
    assert metadata.version == "test-v2"
    assert metadata.content_hash == embedding_content_hash("林岚 找到钥匙")
    assert metadata.embedded_at.tzinfo is not None


def test_live_embedding_request_pins_and_validates_dimensions() -> None:
    service = EmbeddingService(Settings(openai_api_key="test-key"))
    client = FakeEmbeddingClient(EMBEDDING_VECTOR_DIMENSIONS)
    service.client = client

    vector = asyncio.run(service.embed("维度契约"))

    assert len(vector) == EMBEDDING_VECTOR_DIMENSIONS
    assert client.request["dimensions"] == EMBEDDING_VECTOR_DIMENSIONS


def test_live_embedding_rejects_unexpected_dimensions() -> None:
    service = EmbeddingService(Settings(openai_api_key="test-key"))
    service.client = FakeEmbeddingClient(EMBEDDING_VECTOR_DIMENSIONS - 1)

    with pytest.raises(ValueError, match="unexpected vector dimension"):
        asyncio.run(service.embed("错误维度"))


def test_embedding_storage_prefers_fixed_vector_and_preserves_legacy_dimensions() -> None:
    fixed = [0.0] * EMBEDDING_VECTOR_DIMENSIONS
    assert embedding_storage_values(fixed) == (None, fixed)
    assert embedding_storage_values([0.25, 0.75]) == ([0.25, 0.75], None)
    assert stored_embedding(SimpleNamespace(embedding=[0.25], embedding_vector=None)) == [
        0.25
    ]


def test_embedding_storage_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        embedding_storage_values([float("nan")])


def test_embedding_dimension_change_requires_a_schema_migration() -> None:
    with pytest.raises(ValueError, match="fixed pgvector schema dimension"):
        Settings(embedding_dimensions=EMBEDDING_VECTOR_DIMENSIONS // 2)


def test_cosine_similarity_rejects_mixed_dimensions() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0
