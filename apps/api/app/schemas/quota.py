from datetime import datetime

from pydantic import BaseModel, Field


class QuotaResponse(BaseModel):
    limit_tokens: int | None
    used_tokens: int
    remaining_tokens: int | None
    percentage_used: float
    period_started_at: datetime
    resets_at: datetime
    unlimited: bool


class AdminUserQuotaResponse(QuotaResponse):
    id: str
    email: str
    display_name: str
    is_admin: bool
    created_at: datetime


class AdminOverviewResponse(BaseModel):
    total_users: int
    administrator_count: int
    weekly_token_quota: int
    period_started_at: datetime
    resets_at: datetime
    total_used_tokens: int
    users: list[AdminUserQuotaResponse]


class QuotaResetRequest(BaseModel):
    reason: str = Field(default="Manual administrator reset", max_length=220)


class QuotaResetResponse(BaseModel):
    reset_event_id: str
    effective_at: datetime
    resets_at: datetime
