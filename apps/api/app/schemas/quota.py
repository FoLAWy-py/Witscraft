from datetime import datetime

from pydantic import BaseModel, Field


class QuotaResponse(BaseModel):
    limit_tokens: int | None
    used_tokens: int
    remaining_tokens: int | None
    percentage_used: float
    soft_limit_percentage: int
    soft_limit_reached: bool
    period_started_at: datetime
    resets_at: datetime
    unlimited: bool


class AdminUserQuotaResponse(QuotaResponse):
    id: str
    email: str
    display_name: str
    is_admin: bool
    created_at: datetime


class AdminQuotaResetEventResponse(BaseModel):
    id: str
    administrator_email: str | None
    administrator_name: str | None
    reason: str
    effective_at: datetime


class AdminQuotaPolicyChangeResponse(BaseModel):
    id: str
    administrator_email: str | None
    administrator_name: str | None
    previous_limit_tokens: int
    limit_tokens: int
    estimated_words: int
    reason: str
    effective_at: datetime


class AdminOverviewResponse(BaseModel):
    total_users: int
    administrator_count: int
    weekly_token_quota: int
    estimated_weekly_words: int
    period_started_at: datetime
    resets_at: datetime
    total_used_tokens: int
    filtered_users: int
    page: int
    page_size: int
    total_pages: int
    users: list[AdminUserQuotaResponse]
    reset_events: list[AdminQuotaResetEventResponse]
    policy_changes: list[AdminQuotaPolicyChangeResponse]


class QuotaResetRequest(BaseModel):
    reason: str = Field(default="Manual administrator reset", max_length=220)


class QuotaResetResponse(BaseModel):
    reset_event_id: str
    effective_at: datetime
    resets_at: datetime


class QuotaPolicyUpdateRequest(BaseModel):
    weekly_token_quota: int = Field(ge=1000, le=100_000_000)
    reason: str = Field(default="Administrator quota policy update", max_length=220)


class QuotaPolicyUpdateResponse(BaseModel):
    change: AdminQuotaPolicyChangeResponse
