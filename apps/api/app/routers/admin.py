import math
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_admin_user
from app.config import Settings, get_settings
from app.db.models import ModelCall, QuotaResetEvent, User
from app.db.session import get_session
from app.schemas.quota import (
    AdminOverviewResponse,
    AdminQuotaResetEventResponse,
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
    search: str = Query(default="", max_length=120),
    role: Literal["all", "admin", "standard"] = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=10, le=100),
    _admin: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminOverviewResponse:
    period_start, period_end = await quota_period(session)
    total_users, administrator_count = (
        await session.execute(
            select(
                func.count(User.id),
                func.coalesce(func.sum(case((User.is_admin.is_(True), 1), else_=0)), 0),
            )
        )
    ).one()
    normalized_search = search.strip()
    filters = []
    if normalized_search:
        escaped_search = (
            normalized_search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped_search}%"
        filters.append(
            or_(
                User.email.ilike(pattern, escape="\\"),
                func.coalesce(User.display_name, "").ilike(pattern, escape="\\"),
            )
        )
    if role == "admin":
        filters.append(User.is_admin.is_(True))
    elif role == "standard":
        filters.append(User.is_admin.is_(False))

    filtered_users = int(
        await session.scalar(select(func.count(User.id)).where(*filters)) or 0
    )
    total_pages = max(1, math.ceil(filtered_users / page_size))
    current_page = min(page, total_pages)
    users = list(
        (
            await session.execute(
                select(User)
                .where(*filters)
                .order_by(User.created_at.desc(), User.id)
                .offset((current_page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    total_used = int(
        await session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        func.coalesce(ModelCall.input_tokens, 0)
                        + func.coalesce(ModelCall.output_tokens, 0)
                    ),
                    0,
                )
            ).where(
                ModelCall.user_id.is_not(None),
                *quota_usage_predicates(period_start, period_end),
            )
        )
        or 0
    )
    user_ids = [user.id for user in users]
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
                    ModelCall.user_id.in_(user_ids),
                    *quota_usage_predicates(period_start, period_end),
                )
                .group_by(ModelCall.user_id)
            )
        ).all()
    } if user_ids else {}
    reset_rows = (
        await session.execute(
            select(QuotaResetEvent, User.email, User.display_name)
            .outerjoin(User, User.id == QuotaResetEvent.reset_by_user_id)
            .order_by(QuotaResetEvent.effective_at.desc())
            .limit(10)
        )
    ).all()
    rows = []
    for user in users:
        snapshot = quota_snapshot_for_usage(
            user, settings, period_start, period_end, usage.get(user.id, 0)
        )
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
        total_users=int(total_users),
        administrator_count=int(administrator_count),
        weekly_token_quota=settings.user_weekly_token_quota,
        period_started_at=period_start,
        resets_at=period_end,
        total_used_tokens=total_used,
        filtered_users=filtered_users,
        page=current_page,
        page_size=page_size,
        total_pages=total_pages,
        users=rows,
        reset_events=[
            AdminQuotaResetEventResponse(
                id=str(event.id),
                administrator_email=email,
                administrator_name=display_name,
                reason=event.reason,
                effective_at=event.effective_at,
            )
            for event, email, display_name in reset_rows
        ],
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
