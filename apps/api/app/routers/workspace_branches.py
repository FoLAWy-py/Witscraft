"""Branch, summary, and export workspace routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_verified_user_id
from app.config import Settings, get_settings
from app.db.bootstrap import DEFAULT_STORY_ID
from app.db.models import (
    StoryBranch,
)
from app.db.session import get_session
from app.routers.workspace_support import (
    _get_story_branch_for_user,
    _get_story_for_user,
    _parse_uuid,
    workspace,
)
from app.llm.audit import CallAuditor
from app.llm.router import LLMGateway
from app.schemas.chat import (
    CreateBranchRequest,
    GenerateSummaryRequest,
    UpdateBranchRequest,
    WorkspaceResponse,
)
from app.services.branch_manager import clone_story_branch
from app.services.session_summarizer import generate_session_summary
from app.services.model_route_service import load_user_purpose_routes
from app.services.story_exporter import (
    build_story_export_payload,
    export_filename,
    render_story_json,
    render_story_markdown,
)

router = APIRouter()


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
