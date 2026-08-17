import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.config import Settings
from app.services.embeddings import EmbeddingService, cosine_similarity
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


class FakeSession:
    def __init__(self, memories):
        self.memories = memories

    async def execute(self, _query):
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
    assert embedding_service.cache_hits == 1


def test_embedding_batch_uses_one_deterministic_pass_in_dry_run() -> None:
    service = EmbeddingService(Settings(dry_run_llm=True))

    vectors = asyncio.run(service.embed_many(["第一条记忆", "第二条记忆"]))

    assert len(vectors) == 2
    assert all(len(vector) == 128 for vector in vectors)


def test_cosine_similarity_rejects_mixed_dimensions() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0
