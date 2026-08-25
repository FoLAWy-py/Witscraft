"""Memory and canon workspace routes."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_verified_user_id
from app.config import Settings, get_settings
from app.db.bootstrap import DEFAULT_STORY_ID
from app.db.models import (
    CanonFact,
    MemoryItem,
)
from app.db.session import get_session
from app.routers.workspace_support import (
    _get_story_for_user,
    _parse_uuid,
    _parse_uuid_or_none,
    workspace,
)
from app.schemas.chat import (
    UpdateCanonFactRequest,
    UpdateMemoryRequest,
    WorkspaceResponse,
)
from app.services.embeddings import embedding_content_hash
from app.services.canon_corrections import CanonCorrectionError, correct_canon_fact
from app.services.memory_embedding_tasks import enqueue_memory_embedding

router = APIRouter()


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
