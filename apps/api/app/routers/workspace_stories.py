"""Story lifecycle workspace routes."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_verified_user_id
from app.config import Settings, get_settings
from app.db.bootstrap import DEFAULT_STORY_ID
from app.db.models import (
    Character,
    Message,
    Story,
    StoryBranch,
    StoryChapter,
    StoryStateSnapshot,
    StyleProfile,
    World,
)
from app.db.session import get_session
from app.routers.workspace_support import (
    _delete_orphan_world,
    _empty_workspace_response,
    _get_story_for_user,
    _load_worlds,
    _parse_uuid,
    _parse_uuid_or_none,
    workspace,
)
from app.schemas.chat import (
    CreateStoryRequest,
    StoryState,
    UpdateStoryRequest,
    WorkspaceResponse,
)
from app.services.model_route_service import load_user_purpose_routes
from app.services.story_roadmap import plan_initial_roadmap
from app.services.story_chapter_plan import ChapterPlanResizeError, resize_story_chapter_plan

router = APIRouter()


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
