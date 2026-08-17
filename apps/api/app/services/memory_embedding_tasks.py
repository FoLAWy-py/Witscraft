from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import MemoryEmbeddingTask, MemoryItem
from app.db.session import AsyncSessionLocal
from app.llm.audit import CallAuditor
from app.logging_security import redact_sensitive_text
from app.services.embeddings import (
    EmbeddingService,
    embedding_content_hash,
    embedding_storage_values,
    stored_embedding,
)


@dataclass(frozen=True)
class ClaimedMemoryEmbeddingTask:
    memory_id: UUID
    user_id: UUID | None
    story_id: UUID | None
    expected_content_hash: str
    attempts: int
    max_attempts: int
    lease_id: UUID


def memory_embedding_is_compatible(memory: MemoryItem, settings: Settings) -> bool:
    vector = stored_embedding(memory)
    if (
        vector is None
        or memory.content_hash != embedding_content_hash(memory.content)
        or memory.embedded_at is None
    ):
        return False
    return EmbeddingService(settings).is_compatible(
        model=memory.embedding_model,
        dimensions=memory.embedding_dimensions,
        version=memory.embedding_version,
        vector=vector,
    )


def new_memory_embedding_task(
    memory: MemoryItem,
    *,
    max_attempts: int,
) -> MemoryEmbeddingTask:
    content_hash = embedding_content_hash(memory.content)
    memory.content_hash = content_hash
    return MemoryEmbeddingTask(
        memory=memory,
        user_id=memory.user_id,
        story_id=memory.story_id,
        expected_content_hash=content_hash,
        status="pending",
        attempts=0,
        max_attempts=max_attempts,
        available_at=datetime.now(timezone.utc),
    )


async def enqueue_memory_embedding(
    session: AsyncSession,
    memory: MemoryItem,
    *,
    max_attempts: int,
) -> None:
    content_hash = embedding_content_hash(memory.content)
    memory.content_hash = content_hash
    statement = insert(MemoryEmbeddingTask).values(
        memory_id=memory.id,
        user_id=memory.user_id,
        story_id=memory.story_id,
        expected_content_hash=content_hash,
        status="pending",
        attempts=0,
        max_attempts=max_attempts,
        available_at=datetime.now(timezone.utc),
        lease_id=None,
        locked_at=None,
        completed_at=None,
        last_error=None,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[MemoryEmbeddingTask.memory_id],
            set_={
                "user_id": statement.excluded.user_id,
                "story_id": statement.excluded.story_id,
                "expected_content_hash": statement.excluded.expected_content_hash,
                "status": "pending",
                "attempts": 0,
                "max_attempts": statement.excluded.max_attempts,
                "available_at": statement.excluded.available_at,
                "lease_id": None,
                "locked_at": None,
                "completed_at": None,
                "last_error": None,
                "updated_at": datetime.now(timezone.utc),
            },
        )
    )


async def enqueue_incompatible_memories(
    session: AsyncSession,
    settings: Settings,
    *,
    limit: int,
) -> int:
    service = EmbeddingService(settings)
    provider, model = service.provider_and_model()
    expected_model = f"{provider}:{model}"
    memories = list(
        (
            await session.execute(
                select(MemoryItem)
                .where(
                    MemoryItem.is_active.is_(True),
                    or_(
                        MemoryItem.embedding_vector.is_(None),
                        MemoryItem.content_hash.is_(None),
                        MemoryItem.embedded_at.is_(None),
                        MemoryItem.embedding_model.is_distinct_from(expected_model),
                        MemoryItem.embedding_dimensions.is_distinct_from(
                            settings.embedding_dimensions
                        ),
                        MemoryItem.embedding_version.is_distinct_from(
                            settings.embedding_version
                        ),
                    ),
                )
                .order_by(MemoryItem.updated_at.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    for memory in memories:
        await enqueue_memory_embedding(
            session,
            memory,
            max_attempts=settings.memory_embedding_task_max_attempts,
        )
    return len(memories)


async def claim_memory_embedding_tasks(
    settings: Settings,
    *,
    limit: int,
) -> list[ClaimedMemoryEmbeddingTask]:
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=settings.memory_embedding_worker_lease_seconds)
    async with AsyncSessionLocal() as session:
        tasks = list(
            (
                await session.execute(
                    select(MemoryEmbeddingTask)
                    .where(
                        or_(
                            and_(
                                MemoryEmbeddingTask.status.in_(("pending", "retry")),
                                MemoryEmbeddingTask.available_at <= now,
                            ),
                            and_(
                                MemoryEmbeddingTask.status == "running",
                                MemoryEmbeddingTask.locked_at < stale_before,
                            ),
                        )
                    )
                    .order_by(
                        MemoryEmbeddingTask.available_at.asc(),
                        MemoryEmbeddingTask.created_at.asc(),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        claimed = []
        for task in tasks:
            if task.attempts >= task.max_attempts:
                task.status = "dead"
                task.completed_at = now
                task.lease_id = None
                task.locked_at = None
                continue
            lease_id = uuid4()
            task.status = "running"
            task.attempts += 1
            task.lease_id = lease_id
            task.locked_at = now
            task.last_error = None
            claimed.append(
                ClaimedMemoryEmbeddingTask(
                    memory_id=task.memory_id,
                    user_id=task.user_id,
                    story_id=task.story_id,
                    expected_content_hash=task.expected_content_hash,
                    attempts=task.attempts,
                    max_attempts=task.max_attempts,
                    lease_id=lease_id,
                )
            )
        await session.commit()
        return claimed


async def process_memory_embedding_task(
    task: ClaimedMemoryEmbeddingTask,
    settings: Settings,
) -> str:
    try:
        async with AsyncSessionLocal() as session:
            memory = await session.get(MemoryItem, task.memory_id)
            if memory is None:
                return await _finish_task(task, status="succeeded")
            if not memory.is_active:
                return await _finish_task(task, status="superseded")
            if embedding_content_hash(memory.content) != task.expected_content_hash:
                return await _finish_task(task, status="superseded")
            content = memory.content

        auditor = CallAuditor(
            settings,
            user_id=task.user_id,
            story_id=task.story_id,
            request_id=f"memory-embedding-task:{task.memory_id}",
        )
        service = EmbeddingService(settings, auditor=auditor)
        vector = await service.embed(content, purpose="embedding_memory_background")
        metadata = service.metadata(content, vector)
        legacy_embedding, vector_embedding = embedding_storage_values(vector)

        async with AsyncSessionLocal() as session:
            task_row = await session.get(
                MemoryEmbeddingTask,
                task.memory_id,
                with_for_update=True,
            )
            memory = await session.get(MemoryItem, task.memory_id, with_for_update=True)
            if task_row is None or task_row.lease_id != task.lease_id:
                return "lease_lost"
            if memory is None:
                task_row.status = "succeeded"
            elif (
                not memory.is_active
                or embedding_content_hash(memory.content) != task.expected_content_hash
            ):
                task_row.status = "superseded"
            else:
                memory.embedding = legacy_embedding
                memory.embedding_vector = vector_embedding
                memory.embedding_model = metadata.model
                memory.embedding_dimensions = metadata.dimensions
                memory.embedding_version = metadata.version
                memory.content_hash = metadata.content_hash
                memory.embedded_at = metadata.embedded_at
                task_row.status = "succeeded"
            task_row.completed_at = datetime.now(timezone.utc)
            task_row.lease_id = None
            task_row.locked_at = None
            await session.commit()
            return task_row.status
    except Exception as error:
        return await _retry_or_dead_letter(task, error)


async def _finish_task(
    task: ClaimedMemoryEmbeddingTask,
    *,
    status: str,
) -> str:
    async with AsyncSessionLocal() as session:
        row = await session.get(MemoryEmbeddingTask, task.memory_id, with_for_update=True)
        if row is None or row.lease_id != task.lease_id:
            return "lease_lost"
        row.status = status
        row.completed_at = datetime.now(timezone.utc)
        row.lease_id = None
        row.locked_at = None
        await session.commit()
    return status


async def _retry_or_dead_letter(
    task: ClaimedMemoryEmbeddingTask,
    error: BaseException,
) -> str:
    async with AsyncSessionLocal() as session:
        row = await session.get(MemoryEmbeddingTask, task.memory_id, with_for_update=True)
        if row is None or row.lease_id != task.lease_id:
            return "lease_lost"
        now = datetime.now(timezone.utc)
        row.last_error = redact_sensitive_text(f"{type(error).__name__}: {error}")[:1000]
        row.lease_id = None
        row.locked_at = None
        if row.attempts >= row.max_attempts:
            row.status = "dead"
            row.completed_at = now
        else:
            row.status = "retry"
            retry_seconds = min(3600, 30 * (2 ** (row.attempts - 1)))
            row.available_at = now + timedelta(seconds=retry_seconds)
        await session.commit()
        return row.status


async def process_memory_embedding_batch(settings: Settings, *, limit: int) -> dict[str, int]:
    tasks = await claim_memory_embedding_tasks(settings, limit=limit)
    counts: dict[str, int] = {}
    for task in tasks:
        status = await process_memory_embedding_task(task, settings)
        counts[status] = counts.get(status, 0) + 1
    return counts
