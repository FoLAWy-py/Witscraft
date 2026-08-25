"""World and character workspace routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_verified_user_id
from app.db.bootstrap import DEFAULT_CHARACTER_ID, DEFAULT_STORY_ID, DEFAULT_WORLD_ID
from app.db.models import (
    Character,
    Story,
    World,
)
from app.db.session import get_session
from app.routers.workspace_support import (
    _get_story_for_user,
    _parse_uuid,
    workspace,
)
from app.schemas.chat import (
    SetStoryWorldRequest,
    UpdateCharacterRequest,
    UpdateWorldRequest,
    WorkspaceResponse,
)

router = APIRouter()


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
