from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import ModelCall, QuotaPolicyChange, QuotaResetEvent, User


TOKEN_WORD_NUMERATOR = 3
TOKEN_WORD_DENOMINATOR = 4


@dataclass(frozen=True)
class QuotaSnapshot:
    limit_tokens: int | None
    used_tokens: int
    remaining_tokens: int | None
    percentage_used: float
    soft_limit_percentage: int
    soft_limit_reached: bool
    period_started_at: datetime
    resets_at: datetime
    unlimited: bool


class QuotaExceededError(RuntimeError):
    def __init__(
        self,
        snapshot: QuotaSnapshot,
        requested_tokens: int,
    ) -> None:
        self.snapshot = snapshot
        self.requested_tokens = requested_tokens
        self.scope = "account"
        super().__init__("Account weekly AI token quota exceeded")


def estimated_words_for_tokens(tokens: int) -> int:
    """Return the policy's deterministic 4-token-to-3-word estimate."""
    return max(0, tokens) * TOKEN_WORD_NUMERATOR // TOKEN_WORD_DENOMINATOR


async def weekly_token_limit(session: AsyncSession, settings: Settings) -> int:
    persisted = await session.scalar(
        select(QuotaPolicyChange.limit_tokens).order_by(QuotaPolicyChange.id.desc()).limit(1)
    )
    return int(persisted) if persisted is not None else settings.user_weekly_token_quota


def calendar_week(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = (current - timedelta(days=current.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, start + timedelta(days=7)


async def quota_period(session: AsyncSession) -> tuple[datetime, datetime]:
    week_start, week_end = calendar_week()
    latest_reset = await session.scalar(
        select(QuotaResetEvent.effective_at).order_by(QuotaResetEvent.effective_at.desc()).limit(1)
    )
    if latest_reset is not None and latest_reset > week_start:
        return latest_reset, week_end
    return week_start, week_end


async def quota_snapshot(
    session: AsyncSession,
    user: User,
    settings: Settings,
    *,
    period: tuple[datetime, datetime] | None = None,
) -> QuotaSnapshot:
    period_start, period_end = period or await quota_period(session)
    limit_tokens = await weekly_token_limit(session, settings)
    used = int(
        await session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        func.coalesce(ModelCall.input_tokens, 0)
                        + func.coalesce(ModelCall.output_tokens, 0)
                    ),
                    0,
                )
            ).where(ModelCall.user_id == user.id, *quota_usage_predicates(period_start, period_end))
        )
        or 0
    )
    return quota_snapshot_for_usage(
        user,
        settings,
        period_start,
        period_end,
        used,
        limit_tokens=limit_tokens,
    )


def quota_usage_predicates(period_start: datetime, period_end: datetime) -> tuple:
    return (
        ModelCall.status == "succeeded",
        ModelCall.provider != "local",
        func.coalesce(ModelCall.response["dry_run"].as_boolean(), False).is_(False),
        ModelCall.created_at >= period_start,
        ModelCall.created_at < period_end,
    )


def quota_snapshot_for_usage(
    user: User,
    settings: Settings,
    period_start: datetime,
    period_end: datetime,
    used: int,
    *,
    limit_tokens: int | None = None,
) -> QuotaSnapshot:
    if user.is_admin:
        return QuotaSnapshot(
            None,
            used,
            None,
            0.0,
            settings.user_weekly_token_soft_limit_percentage,
            False,
            period_start,
            period_end,
            True,
        )
    limit = limit_tokens if limit_tokens is not None else settings.user_weekly_token_quota
    remaining = max(0, limit - used)
    percentage_used = round(min(100.0, used * 100 / limit), 2)
    soft_limit_reached = (
        used * 100 >= limit * settings.user_weekly_token_soft_limit_percentage
    )
    return QuotaSnapshot(
        limit,
        used,
        remaining,
        percentage_used,
        settings.user_weekly_token_soft_limit_percentage,
        soft_limit_reached,
        period_start,
        period_end,
        False,
    )


async def ensure_quota(
    session: AsyncSession,
    user_id: UUID,
    requested_tokens: int,
    settings: Settings,
) -> QuotaSnapshot:
    user = await session.get(User, user_id)
    if user is None:
        raise RuntimeError("Quota user no longer exists")
    period = await quota_period(session)
    snapshot = await quota_snapshot(session, user, settings, period=period)
    if not snapshot.unlimited and requested_tokens > (snapshot.remaining_tokens or 0):
        raise QuotaExceededError(snapshot, requested_tokens)
    return snapshot


def snapshot_payload(snapshot: QuotaSnapshot) -> dict:
    return {
        "limit_tokens": snapshot.limit_tokens,
        "used_tokens": snapshot.used_tokens,
        "remaining_tokens": snapshot.remaining_tokens,
        "percentage_used": snapshot.percentage_used,
        "soft_limit_percentage": snapshot.soft_limit_percentage,
        "soft_limit_reached": snapshot.soft_limit_reached,
        "period_started_at": snapshot.period_started_at,
        "resets_at": snapshot.resets_at,
        "unlimited": snapshot.unlimited,
    }
