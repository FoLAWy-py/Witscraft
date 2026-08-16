from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_admin_user
from app.config import Settings, get_settings
from app.db.models import ModelCall, QuotaResetEvent, User
from app.db.session import get_session
from app.schemas.quota import (
    AdminOverviewResponse,
    AdminUserQuotaResponse,
    QuotaResetRequest,
    QuotaResetResponse,
)
from app.services.quota_service import (
    calendar_week,
    quota_period,
    quota_snapshot_for_usage,
    quota_usage_predicates,
    snapshot_payload,
)


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=AdminOverviewResponse)
async def overview(
    _admin: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminOverviewResponse:
    users = list((await session.execute(select(User).order_by(User.created_at))).scalars())
    period_start, period_end = await quota_period(session)
    usage = {
        user_id: int(token_count)
        for user_id, token_count in (
            await session.execute(
                select(
                    ModelCall.user_id,
                    func.coalesce(
                        func.sum(
                            func.coalesce(ModelCall.input_tokens, 0)
                            + func.coalesce(ModelCall.output_tokens, 0)
                        ),
                        0,
                    ),
                )
                .where(
                    ModelCall.user_id.is_not(None),
                    *quota_usage_predicates(period_start, period_end),
                )
                .group_by(ModelCall.user_id)
            )
        ).all()
    }
    rows = []
    total_used = 0
    for user in users:
        snapshot = quota_snapshot_for_usage(
            user, settings, period_start, period_end, usage.get(user.id, 0)
        )
        total_used += snapshot.used_tokens
        rows.append(
            AdminUserQuotaResponse(
                id=str(user.id),
                email=user.email,
                display_name=user.display_name or "Author",
                is_admin=user.is_admin,
                created_at=user.created_at,
                **snapshot_payload(snapshot),
            )
        )
    return AdminOverviewResponse(
        total_users=len(users),
        administrator_count=sum(1 for user in users if user.is_admin),
        weekly_token_quota=settings.user_weekly_token_quota,
        period_started_at=period_start,
        resets_at=period_end,
        total_used_tokens=total_used,
        users=rows,
    )


@router.post("/quota/reset-all", response_model=QuotaResetResponse)
async def reset_all_quotas(
    payload: QuotaResetRequest,
    admin: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_session),
) -> QuotaResetResponse:
    now = datetime.now(timezone.utc)
    event = QuotaResetEvent(
        id=uuid4(),
        reset_by_user_id=admin.id,
        reason=payload.reason.strip()[:220] or "Manual administrator reset",
        effective_at=now,
    )
    session.add(event)
    await session.commit()
    _, resets_at = calendar_week(now)
    return QuotaResetResponse(
        reset_event_id=str(event.id), effective_at=now, resets_at=resets_at
    )
