from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.config import Settings, get_settings
from app.db.models import Story, User
from app.db.session import get_session
from app.schemas.quota import QuotaResponse
from app.services.quota_service import quota_snapshot, snapshot_payload, story_quota_snapshot


router = APIRouter(prefix="/quota", tags=["quota"])


@router.get("/me", response_model=QuotaResponse)
async def my_quota(
    story_id: UUID | None = None,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> QuotaResponse:
    user = await session.get(User, user_id)
    if user is None:
        raise RuntimeError("Authenticated user no longer exists")
    payload = snapshot_payload(await quota_snapshot(session, user, settings))
    if story_id is not None:
        story = await session.get(Story, story_id)
        if story is None or story.user_id != user_id:
            raise HTTPException(status_code=404, detail="Story not found")
        story_snapshot = await story_quota_snapshot(session, user, story_id, settings)
        payload.update(
            story_id=str(story_id),
            story_limit_tokens=story_snapshot.limit_tokens,
            story_used_tokens=story_snapshot.used_tokens,
            story_remaining_tokens=story_snapshot.remaining_tokens,
            story_percentage_used=story_snapshot.percentage_used,
        )
    return QuotaResponse(**payload)
