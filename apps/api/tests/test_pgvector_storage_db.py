import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, text

from app.config import Settings
from app.db.models import MemoryItem, Story, StoryBranch, User, World
from app.db.session import AsyncSessionLocal, engine as db_engine
from app.embedding_config import EMBEDDING_VECTOR_DIMENSIONS
from app.services import story_memory_retrieval as memory_retrieval_module
from app.services.embeddings import EmbeddingService, stored_embedding
from app.services.story_engine import StoryEngine
from app.services.turn_context import TurnContext


def test_pgvector_extension_column_and_round_trip() -> None:
    async def scenario() -> None:
        memory_id = uuid4()
        vector = [0.0] * EMBEDDING_VECTOR_DIMENSIONS
        vector[0] = 1.0
        try:
            async with AsyncSessionLocal() as session:
                extension_version = await session.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
                column_type = await session.scalar(
                    text(
                        """
                        SELECT format_type(attribute.atttypid, attribute.atttypmod)
                        FROM pg_attribute AS attribute
                        JOIN pg_class AS relation ON relation.oid = attribute.attrelid
                        WHERE relation.relname = 'memory_items'
                          AND attribute.attname = 'embedding_vector'
                          AND NOT attribute.attisdropped
                        """
                    )
                )
                assert extension_version is not None
                assert column_type == f"vector({EMBEDDING_VECTOR_DIMENSIONS})"

                session.add(
                    MemoryItem(
                        id=memory_id,
                        memory_type="pgvector_contract",
                        content="fixed-dimension vector round trip",
                        entity_tags=[],
                        meta={},
                        embedding=None,
                        embedding_vector=vector,
                        embedding_dimensions=EMBEDDING_VECTOR_DIMENSIONS,
                        is_active=True,
                    )
                )
                await session.commit()

                stored = await session.get(MemoryItem, memory_id)
                assert stored is not None
                assert stored.embedding is None
                round_tripped = stored_embedding(stored)
                assert round_tripped is not None
                assert len(round_tripped) == EMBEDDING_VECTOR_DIMENSIONS
                assert round_tripped[0] == 1.0
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(MemoryItem).where(MemoryItem.id == memory_id))
                await session.commit()
            await db_engine.dispose()

    asyncio.run(scenario())


def test_hybrid_retrieval_uses_exact_database_cosine(monkeypatch) -> None:
    async def scenario() -> None:
        user_id = None
        try:
            async with AsyncSessionLocal() as session:
                user = User(
                    email=f"pgvector-recall-{uuid4()}@example.invalid",
                    display_name="Recall Player",
                    email_verified_at=datetime.now(timezone.utc),
                )
                session.add(user)
                await session.flush()
                user_id = user.id
                world = World(user_id=user.id, name="Recall World", rules={}, lorebook=[], tone={})
                session.add(world)
                await session.flush()
                story = Story(user_id=user.id, world_id=world.id, title="Recall Story")
                session.add(story)
                await session.flush()
                branch = StoryBranch(story_id=story.id, name="Main")
                other_branch = StoryBranch(story_id=story.id, name="Other")
                session.add_all([branch, other_branch])
                await session.flush()
                story.current_branch_id = branch.id

                settings = Settings(dry_run_llm=True, memory_vector_search_min_items=1)
                embedding_service = EmbeddingService(settings)
                query = "铜钥匙"
                query_vector = await embedding_service.embed(query)
                metadata = embedding_service.metadata(query, query_vector)
                opposite_vector = [-value for value in query_vector]
                session.add_all(
                    [
                        MemoryItem(
                            user_id=user.id,
                            story_id=story.id,
                            branch_id=branch.id,
                            memory_type="recall_contract",
                            content="database-match",
                            entity_tags=[],
                            meta={},
                            embedding_vector=query_vector,
                            embedding_model=metadata.model,
                            embedding_dimensions=metadata.dimensions,
                            embedding_version=metadata.version,
                            is_active=True,
                        ),
                        MemoryItem(
                            user_id=user.id,
                            story_id=story.id,
                            branch_id=branch.id,
                            memory_type="recall_contract",
                            content="铜钥匙",
                            entity_tags=["铜钥匙"],
                            meta={},
                            embedding_vector=opposite_vector,
                            embedding_model=metadata.model,
                            embedding_dimensions=metadata.dimensions,
                            embedding_version=metadata.version,
                            is_active=True,
                        ),
                        MemoryItem(
                            user_id=user.id,
                            story_id=story.id,
                            branch_id=other_branch.id,
                            memory_type="recall_contract",
                            content="cross-branch-match",
                            entity_tags=[],
                            meta={},
                            embedding_vector=query_vector,
                            embedding_model=metadata.model,
                            embedding_dimensions=metadata.dimensions,
                            embedding_version=metadata.version,
                            is_active=True,
                        ),
                    ]
                )
                await session.commit()

                def reject_python_vector_scoring(*_args, **_kwargs):
                    raise AssertionError("fixed pgvector rows must not use Python cosine")

                monkeypatch.setattr(
                    memory_retrieval_module,
                    "cosine_similarity",
                    reject_python_vector_scoring,
                )
                engine = StoryEngine.__new__(StoryEngine)
                engine.session = session
                engine.embedding_service = embedding_service
                engine.turn_context = TurnContext()

                retrieved = await engine._load_memories(story.id, branch.id, query)

                relevant = {"database-match"}
                recall_at_one = len(relevant & set(retrieved[:1])) / len(relevant)
                assert recall_at_one == 1.0
                assert "cross-branch-match" not in retrieved
        finally:
            if user_id is not None:
                async with AsyncSessionLocal() as session:
                    await session.execute(delete(User).where(User.id == user_id))
                    await session.commit()
            await db_engine.dispose()

    asyncio.run(scenario())
