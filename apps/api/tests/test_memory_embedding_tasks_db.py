import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete

from app.config import Settings
from app.db.models import MemoryEmbeddingTask, MemoryItem, Story, StoryBranch, User, World
from app.db.session import AsyncSessionLocal, engine as db_engine
from app.services.embeddings import EmbeddingService, embedding_content_hash, stored_embedding
from app.services.memory_embedding_tasks import (
    claim_memory_embedding_tasks,
    enqueue_memory_embedding,
    enqueue_incompatible_memories,
    process_memory_embedding_task,
)


async def _create_memory(content: str) -> tuple[User, MemoryItem]:
    async with AsyncSessionLocal() as session:
        user = User(
            email=f"memory-task-{uuid4()}@example.invalid",
            display_name="Memory Task Player",
            email_verified_at=datetime.now(timezone.utc),
        )
        session.add(user)
        await session.flush()
        world = World(user_id=user.id, name="Task World", rules={}, lorebook=[], tone={})
        session.add(world)
        await session.flush()
        story = Story(user_id=user.id, world_id=world.id, title="Task Story")
        session.add(story)
        await session.flush()
        branch = StoryBranch(story_id=story.id, name="Main")
        session.add(branch)
        await session.flush()
        story.current_branch_id = branch.id
        memory = MemoryItem(
            id=uuid4(),
            user_id=user.id,
            story_id=story.id,
            branch_id=branch.id,
            memory_type="task_contract",
            content=content,
            entity_tags=[],
            meta={},
            is_active=True,
        )
        session.add(memory)
        await enqueue_memory_embedding(session, memory, max_attempts=3)
        await session.commit()
        return user, memory


def test_reenqueue_invalidates_old_lease_and_only_latest_content_is_written() -> None:
    async def scenario() -> None:
        settings = Settings(dry_run_llm=True)
        user, memory = await _create_memory("The player chooses the northern passage")
        try:
            first_claim = (await claim_memory_embedding_tasks(settings, limit=1))[0]
            async with AsyncSessionLocal() as session:
                current = await session.get(MemoryItem, memory.id)
                assert current is not None
                current.content = "The player chooses the moonlit passage"
                await enqueue_memory_embedding(session, current, max_attempts=3)
                await session.commit()

            assert await process_memory_embedding_task(first_claim, settings) == "lease_lost"

            second_claim = (await claim_memory_embedding_tasks(settings, limit=1))[0]
            assert second_claim.expected_content_hash == embedding_content_hash(
                "The player chooses the moonlit passage"
            )
            assert await process_memory_embedding_task(second_claim, settings) == "succeeded"

            async with AsyncSessionLocal() as session:
                stored = await session.get(MemoryItem, memory.id)
                task = await session.get(MemoryEmbeddingTask, memory.id)
                assert stored is not None
                assert task is not None
                assert stored.content_hash == second_claim.expected_content_hash
                assert stored_embedding(stored) is not None
                assert task.status == "succeeded"
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(User).where(User.id == user.id))
                await session.commit()
            await db_engine.dispose()

    asyncio.run(scenario())


def test_terminal_failure_is_dead_lettered_with_redacted_error(monkeypatch) -> None:
    async def fail_embedding(self, text: str, *, purpose: str = "embedding") -> list[float]:
        raise RuntimeError("api_key=provider-secret")

    monkeypatch.setattr(EmbeddingService, "embed", fail_embedding)

    async def scenario() -> None:
        settings = Settings(dry_run_llm=True)
        user, memory = await _create_memory("A durable memory awaiting an embedding")
        try:
            async with AsyncSessionLocal() as session:
                task = await session.get(MemoryEmbeddingTask, memory.id)
                assert task is not None
                task.max_attempts = 1
                await session.commit()

            claim = (await claim_memory_embedding_tasks(settings, limit=1))[0]
            assert await process_memory_embedding_task(claim, settings) == "dead"

            async with AsyncSessionLocal() as session:
                task = await session.get(MemoryEmbeddingTask, memory.id)
                assert task is not None
                assert task.status == "dead"
                assert task.attempts == 1
                assert task.last_error is not None
                assert "provider-secret" not in task.last_error
                assert "[REDACTED]" in task.last_error
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(User).where(User.id == user.id))
                await session.commit()
            await db_engine.dispose()

    asyncio.run(scenario())


def test_expired_lease_at_attempt_limit_is_dead_lettered_without_another_call() -> None:
    async def scenario() -> None:
        settings = Settings(dry_run_llm=True, memory_embedding_worker_lease_seconds=30)
        user, memory = await _create_memory("A worker stopped after its final allowed claim")
        try:
            async with AsyncSessionLocal() as session:
                task = await session.get(MemoryEmbeddingTask, memory.id)
                assert task is not None
                task.status = "running"
                task.attempts = 1
                task.max_attempts = 1
                task.lease_id = uuid4()
                task.locked_at = datetime.now(timezone.utc) - timedelta(seconds=31)
                await session.commit()

            assert await claim_memory_embedding_tasks(settings, limit=1) == []

            async with AsyncSessionLocal() as session:
                task = await session.get(MemoryEmbeddingTask, memory.id)
                assert task is not None
                assert task.status == "dead"
                assert task.attempts == 1
                assert task.lease_id is None
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(User).where(User.id == user.id))
                await session.commit()
            await db_engine.dispose()

    asyncio.run(scenario())


def test_reindex_keeps_current_embedding_and_queues_incompatible_memory() -> None:
    async def scenario() -> None:
        settings = Settings(dry_run_llm=True)
        user, current_memory = await _create_memory("A current compatible memory")
        incompatible_id = uuid4()
        try:
            claim = (await claim_memory_embedding_tasks(settings, limit=1))[0]
            assert await process_memory_embedding_task(claim, settings) == "succeeded"

            async with AsyncSessionLocal() as session:
                session.add(
                    MemoryItem(
                        id=incompatible_id,
                        user_id=user.id,
                        story_id=current_memory.story_id,
                        branch_id=current_memory.branch_id,
                        memory_type="reindex_contract",
                        content="A legacy memory without compatibility metadata",
                        entity_tags=[],
                        meta={},
                        is_active=True,
                    )
                )
                await session.commit()

                queued = await enqueue_incompatible_memories(session, settings, limit=100)
                await session.commit()
                assert queued >= 1

                current_task = await session.get(MemoryEmbeddingTask, current_memory.id)
                incompatible_task = await session.get(MemoryEmbeddingTask, incompatible_id)
                assert current_task is not None
                assert current_task.status == "succeeded"
                assert incompatible_task is not None
                assert incompatible_task.status == "pending"
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(User).where(User.id == user.id))
                await session.commit()
            await db_engine.dispose()

    asyncio.run(scenario())
