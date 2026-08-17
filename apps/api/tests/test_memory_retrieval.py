import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.config import Settings
from app.services.embeddings import EmbeddingService, cosine_similarity, embedding_content_hash
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
    def __init__(self, vector=None):
        self.vector = vector or [0.0, 1.0]
        self.calls = 0
        self.cache_hits = 0

    async def embed(self, _text, **_kwargs):
        self.calls += 1
        return self.vector

    async def record_cache_hit(self, _text, _vector, **_kwargs):
        self.cache_hits += 1

    @staticmethod
    def is_compatible(*, model, dimensions, version, vector):
        return model == "local:test-embedding" and dimensions == len(vector) and version == "test-v1"


def _engine(memories) -> tuple[StoryEngine, CountingEmbeddingService]:
    engine = StoryEngine.__new__(StoryEngine)
    engine.session = FakeSession(memories)
    embedding_service = CountingEmbeddingService()
    engine.embedding_service = embedding_service
    engine.turn_context = TurnContext()
    return engine, embedding_service


def _memory(index: int, embedding=None):
    return SimpleNamespace(
        content=f"memory-{index}",
        importance=5,
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
    assert all(len(vector) == 128 for vector in vectors)


def test_embedding_metadata_binds_content_model_dimensions_and_version() -> None:
    service = EmbeddingService(Settings(dry_run_llm=True, embedding_version="test-v2"))
    vector = asyncio.run(service.embed("  林岚   找到钥匙  "))

    metadata = service.metadata("  林岚   找到钥匙  ", vector)

    assert metadata.model == "local:deterministic-blake2b-128"
    assert metadata.dimensions == 128
    assert metadata.version == "test-v2"
    assert metadata.content_hash == embedding_content_hash("林岚 找到钥匙")
    assert metadata.embedded_at.tzinfo is not None


def test_cosine_similarity_rejects_mixed_dimensions() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0
