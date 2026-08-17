from copy import deepcopy
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    CanonFact,
    MemoryItem,
    Message,
    PlotEvent,
    Story,
    StoryBranch,
    StoryStateSnapshot,
    StorySummary,
)
from app.services.memory_embedding_tasks import (
    memory_embedding_is_compatible,
    new_memory_embedding_task,
)


async def clone_story_branch(
    session: AsyncSession,
    *,
    story: Story,
    source_branch: StoryBranch,
    user_id: UUID,
    name: str,
    settings: Settings,
) -> StoryBranch:
    message_result = await session.execute(
        select(Message)
        .where(Message.story_id == story.id, Message.branch_id == source_branch.id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    source_messages = list(message_result.scalars().all())
    message_ids = {message.id: uuid4() for message in source_messages}

    branch = StoryBranch(
        id=uuid4(),
        story_id=story.id,
        parent_branch_id=source_branch.id,
        name=name,
        created_from_message_id=source_messages[-1].id if source_messages else None,
    )
    session.add(branch)
    await session.flush()

    for message in source_messages:
        session.add(
            Message(
                id=message_ids[message.id],
                story_id=story.id,
                branch_id=branch.id,
                role=message.role,
                content=message.content,
                token_count=message.token_count,
                meta=deepcopy(message.meta or {}),
                created_at=message.created_at,
            )
        )

    snapshot_result = await session.execute(
        select(StoryStateSnapshot)
        .where(StoryStateSnapshot.story_id == story.id, StoryStateSnapshot.branch_id == source_branch.id)
        .order_by(StoryStateSnapshot.created_at.asc(), StoryStateSnapshot.id.asc())
    )
    source_snapshots = list(snapshot_result.scalars().all())
    for snapshot in source_snapshots:
        session.add(
            StoryStateSnapshot(
                story_id=story.id,
                branch_id=branch.id,
                message_id=_mapped_message_id(snapshot.message_id, message_ids),
                state=deepcopy(snapshot.state),
                created_at=snapshot.created_at,
            )
        )
    if not source_snapshots:
        session.add(
            StoryStateSnapshot(
                story_id=story.id,
                branch_id=branch.id,
                state={
                    "location": "未知地点",
                    "time": "未知时间",
                    "mood": "未定义",
                    "objective": "继续推进剧情",
                    "inventory": [],
                    "open_threads": [],
                    "relationships": [],
                },
            )
        )

    memory_result = await session.execute(
        select(MemoryItem).where(
            MemoryItem.story_id == story.id,
            MemoryItem.branch_id == source_branch.id,
        )
    )
    for memory in memory_result.scalars().all():
        cloned_memory = MemoryItem(
            id=uuid4(),
            user_id=memory.user_id or user_id,
            story_id=story.id,
            branch_id=branch.id,
            character_id=memory.character_id,
            memory_type=memory.memory_type,
            content=memory.content,
            importance=memory.importance,
            recency_score=memory.recency_score,
            entity_tags=deepcopy(memory.entity_tags or []),
            meta=deepcopy(memory.meta or {}),
            embedding=deepcopy(memory.embedding),
            embedding_vector=deepcopy(memory.embedding_vector),
            embedding_model=memory.embedding_model,
            embedding_dimensions=memory.embedding_dimensions,
            embedding_version=memory.embedding_version,
            content_hash=memory.content_hash,
            embedded_at=memory.embedded_at,
            source_message_id=_mapped_message_id(memory.source_message_id, message_ids),
            is_active=memory.is_active,
        )
        session.add(cloned_memory)
        if memory.is_active and not memory_embedding_is_compatible(memory, settings):
            cloned_memory.embedding = None
            cloned_memory.embedding_vector = None
            cloned_memory.embedding_model = None
            cloned_memory.embedding_dimensions = None
            cloned_memory.embedding_version = None
            cloned_memory.embedded_at = None
            session.add(
                new_memory_embedding_task(
                    cloned_memory,
                    max_attempts=settings.memory_embedding_task_max_attempts,
                )
            )

    fact_result = await session.execute(
        select(CanonFact).where(
            CanonFact.story_id == story.id,
            CanonFact.branch_id == source_branch.id,
        )
    )
    source_facts = list(fact_result.scalars().all())
    fact_ids = {fact.id: uuid4() for fact in source_facts}
    for fact in source_facts:
        session.add(
            CanonFact(
                id=fact_ids[fact.id],
                story_id=story.id,
                branch_id=branch.id,
                character_id=fact.character_id,
                fact_type=fact.fact_type,
                content=fact.content,
                importance=fact.importance,
                confidence=fact.confidence,
                is_active=fact.is_active,
                source_message_id=_mapped_message_id(fact.source_message_id, message_ids),
                superseded_by=fact_ids.get(fact.superseded_by),
            )
        )

    summary_result = await session.execute(
        select(StorySummary)
        .where(StorySummary.story_id == story.id, StorySummary.branch_id == source_branch.id)
        .order_by(StorySummary.created_at.asc(), StorySummary.id.asc())
    )
    source_summaries = list(summary_result.scalars().all())
    summary_ids = {summary.id: uuid4() for summary in source_summaries}
    for summary in source_summaries:
        session.add(
            StorySummary(
                id=summary_ids[summary.id],
                user_id=user_id,
                story_id=story.id,
                branch_id=branch.id,
                parent_summary_id=summary_ids.get(summary.parent_summary_id),
                from_message_id=_mapped_message_id(summary.from_message_id, message_ids),
                to_message_id=_mapped_message_id(summary.to_message_id, message_ids),
                summary_type=summary.summary_type,
                prompt_version=summary.prompt_version,
                provider=summary.provider,
                model=summary.model,
                trigger=summary.trigger,
                title=summary.title,
                content=summary.content,
                message_count=summary.message_count,
                token_count=summary.token_count,
                created_at=summary.created_at,
            )
        )

    event_result = await session.execute(
        select(PlotEvent)
        .where(PlotEvent.story_id == story.id, PlotEvent.branch_id == source_branch.id)
        .order_by(PlotEvent.created_at.asc(), PlotEvent.id.asc())
    )
    for event in event_result.scalars().all():
        session.add(
            PlotEvent(
                story_id=story.id,
                branch_id=branch.id,
                source_message_id=_mapped_message_id(event.source_message_id, message_ids),
                event_type=event.event_type,
                summary=event.summary,
                characters=deepcopy(event.characters or []),
                locations=deepcopy(event.locations or []),
                objects=deepcopy(event.objects or []),
                importance=event.importance,
                created_at=event.created_at,
            )
        )

    story.current_branch_id = branch.id
    return branch


def _mapped_message_id(message_id: UUID | None, message_ids: dict[UUID, UUID]) -> UUID | None:
    if message_id is None:
        return None
    return message_ids.get(message_id)
