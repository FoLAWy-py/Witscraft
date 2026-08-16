import asyncio
import hashlib
import math
import time
from collections import deque
from dataclasses import dataclass

from fastapi import Request

from app.config import Settings
from app.services.auth_service import SESSION_COOKIE_NAME


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    reset_after: int


class SlidingWindowRateLimiter:
    def __init__(self, max_keys: int = 10000) -> None:
        self.max_keys = max_keys
        self._events: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def check(
        self,
        key: str,
        rule: RateLimitRule,
        *,
        now: float | None = None,
    ) -> RateLimitDecision:
        current = time.monotonic() if now is None else now
        cutoff = current - rule.window_seconds
        async with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= rule.limit:
                retry_after = max(1, math.ceil(events[0] + rule.window_seconds - current))
                return RateLimitDecision(
                    allowed=False,
                    limit=rule.limit,
                    remaining=0,
                    retry_after=retry_after,
                    reset_after=retry_after,
                )
            events.append(current)
            self._prune_keys(current)
            reset_after = max(1, math.ceil(events[0] + rule.window_seconds - current))
            return RateLimitDecision(
                allowed=True,
                limit=rule.limit,
                remaining=max(0, rule.limit - len(events)),
                retry_after=0,
                reset_after=reset_after,
            )

    def _prune_keys(self, now: float) -> None:
        if len(self._events) <= self.max_keys:
            return
        oldest = sorted(
            self._events,
            key=lambda key: self._events[key][-1] if self._events[key] else now,
        )
        for key in oldest[: len(self._events) - self.max_keys]:
            self._events.pop(key, None)


def classify_rate_limit(request: Request, settings: Settings) -> RateLimitRule | None:
    path = request.url.path
    method = request.method
    prefix = settings.api_prefix.rstrip("/")
    if method == "POST" and path == f"{prefix}/auth/register":
        return RateLimitRule("auth_register", settings.rate_limit_register_requests, 3600)
    if method == "POST" and path == f"{prefix}/auth/login":
        return RateLimitRule("auth_login", settings.rate_limit_login_requests, 900)
    if method == "POST" and path.startswith(
        (f"{prefix}/auth/email-verification/", f"{prefix}/auth/password-reset/")
    ):
        return RateLimitRule("auth_email", settings.rate_limit_auth_email_requests, 600)
    if method == "POST" and path == f"{prefix}/providers/test":
        return RateLimitRule("provider_test", settings.rate_limit_provider_test_requests, 60)
    generation_paths = {
        f"{prefix}/chat/send",
        f"{prefix}/chat/stream",
        f"{prefix}/workspace/story-draft",
        f"{prefix}/workspace/story-interview",
        f"{prefix}/workspace/story-interview/stream",
    }
    if method == "POST" and (
        path in generation_paths or path.endswith("/summaries")
    ):
        return RateLimitRule("generation", settings.rate_limit_generation_requests, 60)
    if method == "GET" and path.endswith("/export"):
        return RateLimitRule("export", settings.rate_limit_export_requests, 60)
    return None


def rate_limit_key(request: Request, rule: RateLimitRule) -> str:
    client_ip = request.client.host if request.client else "unknown"
    if rule.name.startswith("auth_"):
        principal = f"ip:{client_ip}"
    else:
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        principal = f"session:{session_token}" if session_token else f"ip:{client_ip}"
    return hashlib.sha256(f"{rule.name}|{principal}".encode()).hexdigest()
