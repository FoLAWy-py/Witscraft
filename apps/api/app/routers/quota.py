from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_session
from app.schemas.quota import QuotaResponse
from app.services.quota_service import quota_snapshot, snapshot_payload


router = APIRouter(prefix="/quota", tags=["quota"])


@router.get("/me", response_model=QuotaResponse)
async def my_quota(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> QuotaResponse:
    user = await session.get(User, user_id)
    if user is None:
        raise RuntimeError("Authenticated user no longer exists")
    return QuotaResponse(**snapshot_payload(await quota_snapshot(session, user, settings)))
