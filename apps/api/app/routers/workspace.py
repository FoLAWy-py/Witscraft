from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import case, delete, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_verified_user_id
from app.config import Settings, get_settings
from app.db.bootstrap import DEFAULT_CHARACTER_ID, DEFAULT_STORY_ID, DEFAULT_WORLD_ID
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
    StyleProfile,
    World,
)
from app.db.session import get_session
from app.routers.workspace_onboarding import router as onboarding_router
from app.llm.audit import CallAuditor
from app.llm.router import LLMGateway
from app.schemas.chat import (
    CreateBranchRequest,
    CreateStoryRequest,
    GenerateSummaryRequest,
    SetStoryWorldRequest,
    StoryState,
    UpdateBranchRequest,
    UpdateCanonFactRequest,
    UpdateCharacterRequest,
    UpdateMemoryRequest,
    UpdateStoryRequest,
    UpdateWorldRequest,
    WorkspaceMessage,
    WorkspaceResponse,
)
from app.services.embeddings import embedding_content_hash, stored_embedding
from app.services.branch_manager import clone_story_branch
from app.services.canon_corrections import CanonCorrectionError, correct_canon_fact
from app.services.memory_embedding_tasks import enqueue_memory_embedding
from app.services.session_summarizer import generate_session_summary
from app.services.model_route_service import load_user_purpose_routes
from app.services.story_exporter import (
    build_story_export_payload,
    export_filename,
    render_story_json,
    render_story_markdown,
)
from app.services.story_roadmap import plan_initial_roadmap
from app.services.story_chapter_plan import ChapterPlanResizeError, resize_story_chapter_plan

router = APIRouter(prefix="/workspace", tags=["workspace"])
router.include_router(onboarding_router)


@router.get("", response_model=WorkspaceResponse)
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


@router.post("/stories", response_model=WorkspaceResponse)
async def create_story(
    request: CreateStoryRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    title = request.title.strip()
    genre = request.genre.strip()
    world_name = request.world_name.strip()
    premise = request.premise.strip()
    protagonist_name = request.protagonist_name.strip()
    protagonist_role = request.protagonist_role.strip()
    tone = request.tone.strip()
    opening_text = request.opening_text.strip()
    custom_prompt = request.custom_prompt.strip()
    if request.opening_mode == "custom" and not opening_text:
        raise HTTPException(status_code=422, detail="Custom opening text is required")

    style_profile_id = None
    if request.style_profile_id:
        requested_profile_id = _parse_uuid_or_none(request.style_profile_id)
        profile = (
            await session.get(StyleProfile, requested_profile_id) if requested_profile_id else None
        )
        if profile is None or profile.user_id != user_id:
            raise HTTPException(status_code=404, detail="Style profile not found")
        style_profile_id = profile.id
    if request.world_id:
        raise HTTPException(
            status_code=422,
            detail="Each novel creates and owns one world; an existing world cannot be reused",
        )

    purpose_routes = await load_user_purpose_routes(session, user_id)
    await session.rollback()
    planned_roadmap = await plan_initial_roadmap(
        request,
        settings=settings,
        user_id=user_id,
        request_id=getattr(http_request.state, "request_id", None),
        purpose_routes=purpose_routes,
    )

    world = World(
        id=uuid4(),
        user_id=user_id,
        name=world_name,
        description=premise,
        genre=genre,
        rules={},
        lorebook=[],
        tone={"style": tone},
    )
    session.add(world)

    character = Character(
        id=uuid4(),
        user_id=user_id,
        world_id=world.id,
        name=protagonist_name,
        description=protagonist_role,
        persona={"identity": protagonist_role, "premise": premise},
        speaking_style={"tone": tone},
        relationship_to_user={},
        constraints={},
    )
    story_id = uuid4()
    branch_id = uuid4()
    story = Story(
        id=story_id,
        user_id=user_id,
        world_id=world.id,
        title=title,
        main_character_id=character.id,
        style_profile_id=style_profile_id,
        current_branch_id=branch_id,
        status="active",
        custom_prompt=custom_prompt or None,
        interaction_mode=request.interaction_mode,
        planned_chapter_count=request.planned_chapter_count,
        minimum_chapter_length=request.minimum_chapter_length,
        chapter_length_unit=request.chapter_length_unit,
        prose_language=request.prose_language.strip(),
    )
    branch = StoryBranch(
        id=branch_id,
        story_id=story_id,
        name="main",
        roadmap_version=1,
        roadmap_source=planned_roadmap.source,
        ending_title=planned_roadmap.draft.ending_title,
    )
    state = StoryState(mood=tone, objective=premise)
    session.add_all([character, story, branch])
    await session.flush()

    snapshot = StoryStateSnapshot(
        story_id=story_id,
        branch_id=branch_id,
        state={
            "location": state.location,
            "time": state.time,
            "mood": state.mood,
            "objective": state.objective,
            "inventory": state.inventory,
            "open_threads": state.open_threads,
            "relationships": [],
        },
    )
    session.add(snapshot)
    chapter_rows = [
        StoryChapter(
            id=uuid4(),
            story_id=story_id,
            branch_id=branch_id,
            chapter_number=chapter.chapter_number,
            title=chapter.title,
            objective=chapter.objective,
            status="active" if chapter.chapter_number == 1 else "planned",
            roadmap_version=1,
        )
        for chapter in planned_roadmap.draft.chapters
    ]
    session.add_all(chapter_rows)
    await session.flush()
    if request.opening_mode == "custom":
        session.add(
            Message(
                id=uuid4(),
                story_id=story_id,
                branch_id=branch_id,
                chapter_id=chapter_rows[0].id,
                role="assistant",
                content=opening_text,
                meta={
                    "chapter_number": 1,
                    "chapter_title": planned_roadmap.draft.chapters[0].title,
                },
            )
        )
    await session.commit()

    return await workspace(story_id=str(story_id), session=session, user_id=user_id)


@router.patch("/stories/{story_id}", response_model=WorkspaceResponse)
async def update_story(
    story_id: str,
    request: UpdateStoryRequest,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_story_id = _parse_uuid(story_id, DEFAULT_STORY_ID)
    if request.planned_chapter_count is not None:
        requested_branch_id = _parse_uuid_or_none(request.branch_id or "")
        if requested_branch_id is None:
            raise HTTPException(status_code=404, detail="Branch not found")
        try:
            story = await resize_story_chapter_plan(
                session,
                story_id=requested_story_id,
                user_id=user_id,
                active_branch_id=requested_branch_id,
                expected_roadmap_version=request.roadmap_version or 0,
                new_chapter_count=request.planned_chapter_count,
            )
        except ChapterPlanResizeError as exc:
            status_code = 404 if exc.code == "not_found" else 409
            raise HTTPException(status_code=status_code, detail=exc.detail) from exc
    else:
        story = await _get_story_for_user(session, requested_story_id, user_id)
        if story is None:
            raise HTTPException(status_code=404, detail="Story not found")

    if request.title is not None:
        story.title = request.title.strip()
    if request.custom_prompt is not None:
        story.custom_prompt = request.custom_prompt.strip() or None
    if request.interaction_mode is not None:
        story.interaction_mode = request.interaction_mode
    if request.consistency_mode is not None:
        story.consistency_mode = request.consistency_mode
    await session.commit()

    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.delete("/stories/{story_id}", response_model=WorkspaceResponse)
async def delete_story(
    story_id: str,
    active_story_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_story_id = _parse_uuid(story_id, DEFAULT_STORY_ID)
    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    total_result = await session.execute(
        select(func.count(Story.id)).where(Story.user_id == user_id)
    )
    if (total_result.scalar_one() or 0) <= 1:
        world_id = story.world_id
        await session.execute(
            delete(Story).where(Story.id == requested_story_id, Story.user_id == user_id)
        )
        await session.flush()
        await _delete_orphan_world(session, world_id, user_id)
        await session.commit()
        return _empty_workspace_response([], await _load_worlds(session, user_id))

    fallback_story = None
    active_id = _parse_uuid(active_story_id or "", DEFAULT_STORY_ID)
    if active_id != requested_story_id:
        fallback_story = await _get_story_for_user(session, active_id, user_id)

    if fallback_story is None:
        fallback_result = await session.execute(
            select(Story)
            .where(Story.user_id == user_id, Story.id != requested_story_id)
            .order_by(desc(Story.updated_at))
            .limit(1)
        )
        fallback_story = fallback_result.scalar_one()

    world_id = story.world_id
    await session.execute(
        delete(Story).where(Story.id == requested_story_id, Story.user_id == user_id)
    )
    await session.flush()
    await _delete_orphan_world(session, world_id, user_id)
    await session.commit()

    return await workspace(story_id=str(fallback_story.id), session=session, user_id=user_id)


@router.post("/stories/{story_id}/branches", response_model=WorkspaceResponse)
async def create_branch(
    story_id: str,
    request: CreateBranchRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_story_id = _parse_uuid(story_id, DEFAULT_STORY_ID)
    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    source_branch_id = story.current_branch_id or UUID("00000000-0000-0000-0000-000000000401")
    source_branch = await session.get(StoryBranch, source_branch_id)
    if source_branch is None or source_branch.story_id != story.id:
        raise HTTPException(status_code=404, detail="Source branch not found")

    branch = await clone_story_branch(
        session,
        story=story,
        source_branch=source_branch,
        user_id=user_id,
        name=request.name.strip() or "新分支",
        settings=settings,
    )
    story.current_branch_id = branch.id
    await session.commit()

    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.patch("/stories/{story_id}/branches/{branch_id}", response_model=WorkspaceResponse)
async def update_branch(
    story_id: str,
    branch_id: str,
    request: UpdateBranchRequest,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    story, branch = await _get_story_branch_for_user(session, story_id, branch_id, user_id)
    branch.name = request.name.strip()
    await session.commit()
    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.post("/stories/{story_id}/branches/{branch_id}/duplicate", response_model=WorkspaceResponse)
async def duplicate_branch(
    story_id: str,
    branch_id: str,
    request: CreateBranchRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    story, source_branch = await _get_story_branch_for_user(session, story_id, branch_id, user_id)
    await clone_story_branch(
        session,
        story=story,
        source_branch=source_branch,
        user_id=user_id,
        name=request.name.strip() or f"{source_branch.name} copy",
        settings=settings,
    )
    await session.commit()
    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.delete("/stories/{story_id}/branches/{branch_id}", response_model=WorkspaceResponse)
async def delete_branch(
    story_id: str,
    branch_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    story, branch = await _get_story_branch_for_user(session, story_id, branch_id, user_id)
    count_result = await session.execute(
        select(func.count(StoryBranch.id)).where(StoryBranch.story_id == story.id)
    )
    if (count_result.scalar_one() or 0) <= 1:
        raise HTTPException(status_code=409, detail="Cannot delete the final branch")

    fallback_branch = None
    if branch.parent_branch_id is not None:
        parent = await session.get(StoryBranch, branch.parent_branch_id)
        if parent is not None and parent.story_id == story.id:
            fallback_branch = parent
    if fallback_branch is None:
        fallback_result = await session.execute(
            select(StoryBranch)
            .where(StoryBranch.story_id == story.id, StoryBranch.id != branch.id)
            .order_by(StoryBranch.created_at.asc(), StoryBranch.id.asc())
            .limit(1)
        )
        fallback_branch = fallback_result.scalar_one()

    await session.execute(
        update(StoryBranch)
        .where(StoryBranch.parent_branch_id == branch.id)
        .values(parent_branch_id=branch.parent_branch_id)
    )
    if story.current_branch_id == branch.id:
        story.current_branch_id = fallback_branch.id
    await session.execute(delete(StoryBranch).where(StoryBranch.id == branch.id))
    await session.commit()
    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.patch("/stories/{story_id}/branches/{branch_id}/activate", response_model=WorkspaceResponse)
async def activate_branch(
    story_id: str,
    branch_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_story_id = _parse_uuid(story_id, DEFAULT_STORY_ID)
    requested_branch_id = _parse_uuid(branch_id, UUID("00000000-0000-0000-0000-000000000401"))
    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    branch = await session.get(StoryBranch, requested_branch_id)
    if branch is None or branch.story_id != story.id:
        raise HTTPException(status_code=404, detail="Branch not found")

    story.current_branch_id = branch.id
    await session.commit()

    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.post("/stories/{story_id}/branches/{branch_id}/summaries", response_model=WorkspaceResponse)
async def create_summary(
    story_id: str,
    branch_id: str,
    http_request: Request,
    request: GenerateSummaryRequest | None = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    del request
    requested_story_id = _parse_uuid(story_id, DEFAULT_STORY_ID)
    requested_branch_id = _parse_uuid(branch_id, UUID("00000000-0000-0000-0000-000000000401"))
    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    branch = await session.get(StoryBranch, requested_branch_id)
    if branch is None or branch.story_id != story.id:
        raise HTTPException(status_code=404, detail="Branch not found")

    try:
        auditor = CallAuditor(
            settings,
            user_id=user_id,
            story_id=story.id,
            request_id=getattr(http_request.state, "request_id", None),
        )
        await generate_session_summary(
            session,
            LLMGateway(
                settings,
                auditor=auditor,
                purpose_routes=await load_user_purpose_routes(session, user_id),
            ),
            story,
            branch,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.get("/stories/{story_id}/branches/{branch_id}/export")
async def export_story(
    story_id: str,
    branch_id: str,
    format: str = "markdown",
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> Response:
    requested_story_id = _parse_uuid(story_id, DEFAULT_STORY_ID)
    requested_branch_id = _parse_uuid(branch_id, UUID("00000000-0000-0000-0000-000000000401"))
    story = await _get_story_for_user(session, requested_story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    branch = await session.get(StoryBranch, requested_branch_id)
    if branch is None or branch.story_id != story.id:
        raise HTTPException(status_code=404, detail="Branch not found")

    payload = await build_story_export_payload(session, story, branch)
    normalized_format = format.strip().lower()
    if normalized_format in {"markdown", "md"}:
        content = render_story_markdown(payload)
        filename = export_filename(story.title, branch.name, "md")
        media_type = "text/markdown; charset=utf-8"
    elif normalized_format == "json":
        content = render_story_json(payload)
        filename = export_filename(story.title, branch.name, "json")
        media_type = "application/json; charset=utf-8"
    else:
        raise HTTPException(status_code=422, detail="Export format must be markdown or json")

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/worlds/{world_id}", response_model=WorkspaceResponse)
async def update_world(
    world_id: str,
    request: UpdateWorldRequest,
    active_story_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_world_id = _parse_uuid(world_id, DEFAULT_WORLD_ID)
    world = await session.get(World, requested_world_id)
    if world is None or world.user_id != user_id:
        raise HTTPException(status_code=404, detail="World not found")

    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="World name cannot be empty")

    world.name = name
    world.description = request.description.strip()
    world.genre = request.genre.strip()
    await session.commit()

    active_id = _parse_uuid(active_story_id or "", DEFAULT_STORY_ID)
    active_story = await _get_story_for_user(session, active_id, user_id)
    if active_story is None:
        result = await session.execute(
            select(Story)
            .where(Story.user_id == user_id, Story.world_id == world.id)
            .order_by(desc(Story.updated_at))
            .limit(1)
        )
        active_story = result.scalar_one_or_none()

    return await workspace(
        story_id=str(active_story.id if active_story else DEFAULT_STORY_ID),
        session=session,
        user_id=user_id,
    )


@router.post("/worlds", response_model=WorkspaceResponse)
async def create_world(
    request: UpdateWorldRequest,
    active_story_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    del request, active_story_id, session, user_id
    raise HTTPException(
        status_code=409,
        detail="Each novel owns one world; edit the current novel's world instead",
    )


@router.patch("/stories/{story_id}/world", response_model=WorkspaceResponse)
async def set_story_world(
    story_id: str,
    request: SetStoryWorldRequest,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    del story_id, request, session, user_id
    raise HTTPException(
        status_code=409,
        detail="A novel's world cannot be switched after creation",
    )


@router.delete("/worlds/{world_id}", response_model=WorkspaceResponse)
async def delete_world(
    world_id: str,
    active_story_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_world_id = _parse_uuid(world_id, DEFAULT_WORLD_ID)
    world = await session.get(World, requested_world_id)
    if world is None or world.user_id != user_id:
        raise HTTPException(status_code=404, detail="World not found")
    story_count = await session.scalar(
        select(func.count(Story.id)).where(Story.user_id == user_id, Story.world_id == world.id)
    )
    if story_count:
        raise HTTPException(status_code=409, detail="World is still used by a story")

    await session.execute(
        delete(Character).where(Character.user_id == user_id, Character.world_id == world.id)
    )
    await session.delete(world)
    await session.commit()
    return await workspace(story_id=active_story_id, session=session, user_id=user_id)


@router.patch("/characters/{character_id}", response_model=WorkspaceResponse)
async def update_character(
    character_id: str,
    request: UpdateCharacterRequest,
    active_story_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_character_id = _parse_uuid(character_id, DEFAULT_CHARACTER_ID)
    character = await session.get(Character, requested_character_id)
    if character is None or character.user_id != user_id:
        raise HTTPException(status_code=404, detail="Character not found")

    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Character name cannot be empty")

    character.name = name
    character.description = request.role.strip()
    await session.commit()

    active_id = _parse_uuid(active_story_id or "", DEFAULT_STORY_ID)
    active_story = await _get_story_for_user(session, active_id, user_id)
    if active_story is None:
        result = await session.execute(
            select(Story)
            .where(Story.user_id == user_id, Story.world_id == character.world_id)
            .order_by(desc(Story.updated_at))
            .limit(1)
        )
        active_story = result.scalar_one_or_none()

    return await workspace(
        story_id=str(active_story.id if active_story else DEFAULT_STORY_ID),
        session=session,
        user_id=user_id,
    )


@router.post("/worlds/{world_id}/characters", response_model=WorkspaceResponse)
async def create_character(
    world_id: str,
    request: UpdateCharacterRequest,
    active_story_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    world = await session.get(World, _parse_uuid(world_id, DEFAULT_WORLD_ID))
    if world is None or world.user_id != user_id:
        raise HTTPException(status_code=404, detail="World not found")
    story = await _get_story_for_user(
        session,
        _parse_uuid(active_story_id, DEFAULT_STORY_ID),
        user_id,
    )
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Character name cannot be empty")
    character = Character(
        user_id=user_id,
        world_id=world.id,
        name=name,
        description=request.role.strip(),
        persona={"identity": request.role.strip()},
        speaking_style={},
        relationship_to_user={},
        constraints={},
    )
    session.add(character)
    await session.flush()
    if story.world_id == world.id and story.main_character_id is None:
        story.main_character_id = character.id
    await session.commit()
    return await workspace(story_id=str(story.id), session=session, user_id=user_id)


@router.delete("/characters/{character_id}", response_model=WorkspaceResponse)
async def delete_character(
    character_id: str,
    active_story_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    character = await session.get(
        Character,
        _parse_uuid(character_id, DEFAULT_CHARACTER_ID),
    )
    if character is None or character.user_id != user_id:
        raise HTTPException(status_code=404, detail="Character not found")
    main_count = await session.scalar(
        select(func.count(Story.id)).where(
            Story.user_id == user_id,
            Story.main_character_id == character.id,
        )
    )
    if main_count:
        raise HTTPException(status_code=409, detail="A story's main character cannot be deleted")

    await session.delete(character)
    await session.commit()
    return await workspace(story_id=active_story_id, session=session, user_id=user_id)


@router.patch("/memories/{memory_id}", response_model=WorkspaceResponse)
async def update_memory(
    memory_id: str,
    request: UpdateMemoryRequest,
    http_request: Request,
    active_story_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_memory_id = _parse_uuid(memory_id, uuid4())
    memory = await session.get(MemoryItem, requested_memory_id)
    if memory is None or memory.user_id != user_id:
        raise HTTPException(status_code=404, detail="Memory not found")

    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Memory content cannot be empty")

    content_hash = embedding_content_hash(content)
    duplicate_id = await session.scalar(
        select(MemoryItem.id)
        .where(
            MemoryItem.id != memory.id,
            MemoryItem.user_id == user_id,
            MemoryItem.story_id == memory.story_id,
            MemoryItem.branch_id == memory.branch_id,
            MemoryItem.is_active.is_(True),
            or_(
                MemoryItem.content_hash == content_hash,
                MemoryItem.content == content,
            ),
        )
        .limit(1)
    )
    if duplicate_id is not None:
        raise HTTPException(
            status_code=409, detail="An active memory with this content already exists"
        )

    content_changed = memory.content_hash != content_hash
    memory.content = content
    memory.importance = request.importance
    if content_changed:
        memory.entity_tags = []
        memory.embedding = None
        memory.embedding_vector = None
        memory.embedding_model = None
        memory.embedding_dimensions = None
        memory.embedding_version = None
        memory.content_hash = None
        memory.embedded_at = None
        await enqueue_memory_embedding(
            session,
            memory,
            max_attempts=settings.memory_embedding_task_max_attempts,
        )
    await session.commit()

    active_id = _parse_uuid(active_story_id or "", memory.story_id or DEFAULT_STORY_ID)
    return await workspace(story_id=str(active_id), session=session, user_id=user_id)


@router.patch("/canon-facts/{fact_id}", response_model=WorkspaceResponse)
async def update_canon_fact(
    fact_id: str,
    request: UpdateCanonFactRequest,
    active_story_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> WorkspaceResponse:
    requested_fact_id = _parse_uuid(fact_id, uuid4())
    fact = await session.get(CanonFact, requested_fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Canon fact not found")
    story = await _get_story_for_user(session, fact.story_id, user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Canon fact not found")
    if not fact.is_active:
        raise HTTPException(
            status_code=409, detail="The canon fact changed; reload before editing it"
        )

    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Canon fact content cannot be empty")

    if content != fact.content:
        requested_branch_id = _parse_uuid_or_none(request.branch_id or "")
        if (
            request.expected_content is None
            or requested_branch_id is None
            or request.branch_version is None
            or request.roadmap_version is None
        ):
            raise HTTPException(
                status_code=409,
                detail="Reload canon and confirm the affected future roadmap before correcting it",
            )
        try:
            fact = await correct_canon_fact(
                session,
                fact_id=fact.id,
                user_id=user_id,
                new_content=content,
                importance=request.importance,
                expected_content=request.expected_content,
                branch_id=requested_branch_id,
                expected_branch_version=request.branch_version,
                expected_roadmap_version=request.roadmap_version,
                confirmed=request.confirm_future_invalidation,
            )
        except CanonCorrectionError as exc:
            status_code = 404 if exc.code == "not_found" else 409
            raise HTTPException(status_code=status_code, detail=exc.detail) from exc
    else:
        fact.importance = request.importance
    await session.commit()

    active_id = _parse_uuid(active_story_id or "", fact.story_id or DEFAULT_STORY_ID)
    return await workspace(story_id=str(active_id), session=session, user_id=user_id)


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
