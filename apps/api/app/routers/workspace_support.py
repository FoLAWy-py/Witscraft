"""Authorized workspace hydration and shared ownership-query helpers."""

from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import case, delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_verified_user_id
from app.db.models import (
    CanonFact,
    Character,
    MemoryItem,
    Message,
    ModelCall,
    Story,
    StoryBranch,
    StoryChapter,
    StorySummary,
    StoryStateSnapshot,
    World,
)
from app.db.session import get_session
from app.schemas.chat import StoryState, WorkspaceMessage, WorkspaceResponse
from app.services.embeddings import stored_embedding


async def workspace(
    story_id: str | None = None,
    branch_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    stories = await _load_stories(session, user_id)
    worlds = await _load_worlds(session, user_id)
    story = None
    if story_id:
        requested_story_id = _parse_uuid_or_none(story_id)
        if requested_story_id is not None:
            story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        result = await session.execute(
            select(Story).where(Story.user_id == user_id).order_by(Story.created_at.asc()).limit(1)
        )
        story = result.scalar_one_or_none()
    if story is None:
        return _empty_workspace_response(stories, worlds)

    active_branch_id = story.current_branch_id
    requested_branch_id = _parse_uuid_or_none(branch_id or "")
    if requested_branch_id is not None:
        requested_branch = await session.get(StoryBranch, requested_branch_id)
        if requested_branch is not None and requested_branch.story_id == story.id:
            active_branch_id = requested_branch.id
    if active_branch_id is None:
        fallback_branch = await session.scalar(
            select(StoryBranch)
            .where(StoryBranch.story_id == story.id)
            .order_by(StoryBranch.created_at.asc())
            .limit(1)
        )
        active_branch_id = (
            fallback_branch.id
            if fallback_branch is not None
            else UUID("00000000-0000-0000-0000-000000000401")
        )

    branches = await _load_branches(session, story.id, active_branch_id)
    world = await _load_world(session, story.world_id, user_id)
    characters = await _load_characters(session, story.world_id, user_id, story.main_character_id)
    messages = await _load_messages(session, story.id, active_branch_id)
    state, relationships = await _load_state(session, story.id, active_branch_id)
    memory_items = await _load_memory_items(session, story.id, active_branch_id)
    canon_fact_items = await _load_canon_fact_items(session, story.id, active_branch_id)
    summaries = await _load_summaries(session, story.id, active_branch_id)
    model_call = await _load_model_call(session, story.id)
    active_branch = await session.get(StoryBranch, active_branch_id)
    chapters = await _load_chapters(session, story.id, active_branch_id)
    protected_chapter_number = await session.scalar(
        select(func.max(StoryChapter.chapter_number)).where(
            StoryChapter.story_id == story.id,
            StoryChapter.status.in_(("active", "completed")),
        )
    )

    return WorkspaceResponse(
        story_id=str(story.id),
        branch_id=str(active_branch_id),
        branches=branches,
        stories=stories,
        world=world,
        worlds=worlds,
        characters=characters,
        messages=messages,
        story_state=state,
        relationships=relationships,
        retrieved_memories=[memory["content"] for memory in memory_items],
        canon_facts=[fact["content"] for fact in canon_fact_items],
        memory_items=memory_items,
        canon_fact_items=canon_fact_items,
        summaries=summaries,
        model_call=model_call,
        onboarding_required=False,
        story_prompt=story.custom_prompt or "",
        interaction_mode=story.interaction_mode or "choices",
        consistency_mode=story.consistency_mode or "auto",
        planned_chapter_count=story.planned_chapter_count,
        minimum_planned_chapter_count=max(3, protected_chapter_number or 0),
        minimum_chapter_length=story.minimum_chapter_length,
        chapter_length_unit=story.chapter_length_unit,
        prose_language=story.prose_language,
        roadmap_version=active_branch.roadmap_version if active_branch else 0,
        roadmap_source=active_branch.roadmap_source if active_branch else "legacy",
        ending_title=active_branch.ending_title or "" if active_branch else "",
        chapters=chapters,
    )


async def _load_stories(session: AsyncSession, user_id: UUID) -> list[dict]:
    result = await session.execute(
        select(Story, World.name)
        .outerjoin(World, Story.world_id == World.id)
        .where(Story.user_id == user_id)
        .order_by(desc(Story.updated_at))
    )
    return [
        {
            "id": str(story.id),
            "title": story.title,
            "world": world_name or "",
            "updated": story.updated_at.isoformat() if story.updated_at else "",
            "wordCount": 0,
            "status": story.status,
        }
        for story, world_name in result.all()
    ]


def _empty_workspace_response(stories: list[dict], worlds: list[dict]) -> WorkspaceResponse:
    return WorkspaceResponse(
        story_id="",
        branch_id="",
        branches=[],
        stories=stories,
        world={},
        worlds=worlds,
        characters=[],
        messages=[],
        story_state=StoryState(),
        relationships=[],
        retrieved_memories=[],
        canon_facts=[],
        memory_items=[],
        canon_fact_items=[],
        summaries=[],
        model_call=None,
        onboarding_required=True,
        story_prompt="",
    )


async def _delete_orphan_world(
    session: AsyncSession,
    world_id: UUID | None,
    user_id: UUID,
) -> None:
    if world_id is None:
        return
    story_count = await session.scalar(
        select(func.count(Story.id)).where(Story.world_id == world_id, Story.user_id == user_id)
    )
    if story_count:
        return
    await session.execute(
        delete(Character).where(Character.world_id == world_id, Character.user_id == user_id)
    )
    await session.execute(delete(World).where(World.id == world_id, World.user_id == user_id))


async def _load_worlds(session: AsyncSession, user_id: UUID) -> list[dict]:
    result = await session.execute(
        select(World, func.count(Story.id))
        .outerjoin(Story, (Story.world_id == World.id) & (Story.user_id == user_id))
        .where(World.user_id == user_id)
        .group_by(World.id)
        .order_by(desc(World.updated_at), World.name.asc())
    )
    return [
        {
            "id": str(world.id),
            "name": world.name,
            "genre": world.genre or "",
            "story_count": story_count,
        }
        for world, story_count in result.all()
    ]


async def _load_branches(
    session: AsyncSession, story_id: UUID, active_branch_id: UUID
) -> list[dict]:
    result = await session.execute(
        select(StoryBranch)
        .where(StoryBranch.story_id == story_id)
        .order_by(StoryBranch.created_at.asc())
    )
    return [
        {
            "id": str(branch.id),
            "name": branch.name,
            "parent_branch_id": str(branch.parent_branch_id) if branch.parent_branch_id else None,
            "created_at": branch.created_at.isoformat() if branch.created_at else "",
            "active": branch.id == active_branch_id,
            "version": branch.version,
            "roadmap_version": branch.roadmap_version,
            "roadmap_source": branch.roadmap_source,
            "ending_title": branch.ending_title or "",
        }
        for branch in result.scalars().all()
    ]


async def _load_world(session: AsyncSession, world_id, user_id: UUID) -> dict:
    if world_id is None:
        return {}
    world = await session.get(World, world_id)
    if world is None or world.user_id != user_id:
        return {}
    return {
        "id": str(world.id),
        "name": world.name,
        "description": world.description,
        "genre": world.genre,
        "rules": world.rules,
        "lorebook": world.lorebook,
        "tone": world.tone,
    }


async def _load_characters(
    session: AsyncSession,
    world_id,
    user_id: UUID,
    main_character_id: UUID | None,
) -> list[dict]:
    query = select(Character).where(Character.user_id == user_id)
    if world_id is not None:
        query = query.where(Character.world_id == world_id)
    result = await session.execute(query.order_by(Character.created_at.asc()))
    characters = []
    for character in result.scalars().all():
        characters.append(
            {
                "id": str(character.id),
                "name": character.name,
                "role": character.description or character.persona.get("identity", ""),
                "present": True,
                "initials": character.name[:1],
                "main": character.id == main_character_id,
            }
        )
    return characters


async def _load_messages(
    session: AsyncSession, story_id: UUID, branch_id: UUID
) -> list[WorkspaceMessage]:
    result = await session.execute(
        select(Message)
        .where(Message.story_id == story_id, Message.branch_id == branch_id)
        .order_by(
            Message.created_at.asc(),
            case((Message.role == "user", 0), (Message.role == "assistant", 1), else_=2),
            Message.id.asc(),
        )
        .limit(80)
    )
    return [
        WorkspaceMessage(
            id=str(message.id),
            role=message.role,
            content=message.content,
            author=message.meta.get("author") if message.meta else None,
            time=message.meta.get("time") if message.meta else None,
            choices=message.meta.get("choices", []) if message.meta else [],
            consistency_check=message.meta.get("consistency_check") if message.meta else None,
            chapter_id=str(message.chapter_id) if message.chapter_id else None,
        )
        for message in result.scalars().all()
    ]


async def _load_chapters(
    session: AsyncSession,
    story_id: UUID,
    branch_id: UUID,
) -> list[dict]:
    result = await session.execute(
        select(StoryChapter)
        .where(StoryChapter.story_id == story_id, StoryChapter.branch_id == branch_id)
        .order_by(StoryChapter.chapter_number.asc())
    )
    return [
        {
            "id": str(chapter.id),
            "number": chapter.chapter_number,
            "title": chapter.title,
            "objective": chapter.objective or "",
            "status": chapter.status,
            "roadmap_version": chapter.roadmap_version,
            "message_id": str(chapter.message_id) if chapter.message_id else None,
            "completed_at": chapter.completed_at.isoformat() if chapter.completed_at else None,
        }
        for chapter in result.scalars().all()
    ]


async def _load_state(session: AsyncSession, story_id: UUID, branch_id: UUID):
    result = await session.execute(
        select(StoryStateSnapshot)
        .where(StoryStateSnapshot.story_id == story_id, StoryStateSnapshot.branch_id == branch_id)
        .order_by(desc(StoryStateSnapshot.created_at))
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        return StoryState(), []
    state = StoryState(
        location=snapshot.state.get("location", "未知地点"),
        time=snapshot.state.get("time", "未知时间"),
        mood=snapshot.state.get("mood", "未定义"),
        objective=snapshot.state.get("objective", "继续推进剧情"),
        inventory=snapshot.state.get("inventory", []),
        open_threads=snapshot.state.get("open_threads", []),
    )
    return state, snapshot.state.get("relationships", [])


async def _load_memory_items(session: AsyncSession, story_id: UUID, branch_id: UUID) -> list[dict]:
    result = await session.execute(
        select(MemoryItem)
        .where(
            MemoryItem.story_id == story_id,
            MemoryItem.branch_id == branch_id,
            MemoryItem.is_active.is_(True),
        )
        .order_by(
            case((MemoryItem.meta["source"].astext == "llm_state_extractor", 0), else_=1),
            desc(MemoryItem.importance),
            desc(MemoryItem.updated_at),
        )
        .limit(8)
    )
    return [
        {
            "id": str(memory.id),
            "content": memory.content,
            "importance": memory.importance,
            "type": memory.memory_type,
            "has_embedding": stored_embedding(memory) is not None,
            "embedding_model": memory.embedding_model,
            "embedding_dimensions": memory.embedding_dimensions
            or len(stored_embedding(memory) or []),
            "embedding_version": memory.embedding_version,
        }
        for memory in result.scalars().all()
    ]


async def _load_canon_fact_items(
    session: AsyncSession, story_id: UUID, branch_id: UUID
) -> list[dict]:
    result = await session.execute(
        select(CanonFact)
        .where(
            CanonFact.story_id == story_id,
            CanonFact.branch_id == branch_id,
            CanonFact.is_active.is_(True),
        )
        .order_by(
            case((CanonFact.fact_type == "llm_state_extraction", 0), else_=1),
            desc(CanonFact.importance),
            desc(CanonFact.created_at),
        )
        .limit(12)
    )
    return [
        {
            "id": str(fact.id),
            "content": fact.content,
            "importance": fact.importance,
            "type": fact.fact_type,
        }
        for fact in result.scalars().all()
    ]


async def _load_summaries(session: AsyncSession, story_id: UUID, branch_id: UUID) -> list[dict]:
    result = await session.execute(
        select(StorySummary)
        .where(StorySummary.story_id == story_id, StorySummary.branch_id == branch_id)
        .order_by(desc(StorySummary.created_at))
        .limit(6)
    )
    return [
        {
            "id": str(summary.id),
            "parent_summary_id": (
                str(summary.parent_summary_id) if summary.parent_summary_id else None
            ),
            "title": summary.title,
            "content": summary.content,
            "type": summary.summary_type,
            "prompt_version": summary.prompt_version,
            "provider": summary.provider,
            "model": summary.model,
            "trigger": summary.trigger,
            "message_count": summary.message_count,
            "token_count": summary.token_count,
            "created_at": summary.created_at.isoformat() if summary.created_at else "",
        }
        for summary in result.scalars().all()
    ]


async def _load_model_call(session: AsyncSession, story_id: UUID) -> dict | None:
    result = await session.execute(
        select(ModelCall)
        .where(
            ModelCall.story_id == story_id,
            ModelCall.call_type == "llm",
            ModelCall.status == "succeeded",
            ModelCall.purpose.in_(("normal_chat", "critical_story_generation")),
        )
        .order_by(desc(ModelCall.created_at))
        .limit(1)
    )
    call = result.scalar_one_or_none()
    if call is None:
        return None
    return {
        "id": str(call.id),
        "provider": call.provider,
        "model": call.model,
        "purpose": call.purpose,
        "latency_ms": call.latency_ms,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "cost_estimate": float(call.cost_estimate) if call.cost_estimate is not None else None,
        "turn_id": str(call.turn_id) if call.turn_id else None,
        "request_id": call.request_id,
        "status": call.status,
        "pricing_version": call.pricing_version,
        "dry_run": call.response.get("dry_run", False) if call.response else False,
    }


async def _get_story_for_user(session: AsyncSession, story_id: UUID, user_id: UUID) -> Story | None:
    result = await session.execute(
        select(Story).where(Story.id == story_id, Story.user_id == user_id).limit(1)
    )
    return result.scalar_one_or_none()


async def _get_story_branch_for_user(
    session: AsyncSession,
    story_id: str,
    branch_id: str,
    user_id: UUID,
) -> tuple[Story, StoryBranch]:
    try:
        requested_story_id = UUID(story_id)
        requested_branch_id = UUID(branch_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Story or branch not found") from error

    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")
    branch = await session.get(StoryBranch, requested_branch_id)
    if branch is None or branch.story_id != story.id:
        raise HTTPException(status_code=404, detail="Branch not found")
    return story, branch


def _parse_uuid(value: str, fallback: UUID) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        return fallback


def _parse_uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None
