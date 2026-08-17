import asyncio

from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import Settings
from app.main import create_app
from app.services.auth_service import SESSION_COOKIE_NAME
from app.services.rate_limiter import (
    RateLimitRule,
    SlidingWindowRateLimiter,
    classify_rate_limit,
    rate_limit_key,
)


def _request(path: str, method: str = "POST", *, cookie: str | None = None) -> Request:
    headers = []
    if cookie:
        headers.append((b"cookie", f"{SESSION_COOKIE_NAME}={cookie}".encode()))
    return Request(
        {
            "type": "http",
            "scheme": "https",
            "server": ("app.example.com", 443),
            "client": ("192.0.2.20", 1234),
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": headers,
        }
    )


def _production_settings(**updates) -> Settings:
    values = {
        "app_environment": "production",
        "frontend_base_url": "https://app.example.com/witscraft",
        "cors_origins": ["https://app.example.com"],
        "cors_origin_regex": None,
        "allowed_hosts": ["app.example.com", "testserver"],
        "database_username": "database-user",
        "database_password": "database-password",
        "deepinfra_api_key": "provider-key",
        "smtp_host": "smtp.example.com",
        "smtp_username": "smtp-user",
        "smtp_password": "smtp-password",
        "smtp_from_email": "noreply@example.com",
    }
    values.update(updates)
    return Settings(**values)


def test_sliding_window_releases_capacity_after_window() -> None:
    limiter = SlidingWindowRateLimiter()
    rule = RateLimitRule("test", limit=2, window_seconds=10)

    first = asyncio.run(limiter.check("key", rule, now=0))
    second = asyncio.run(limiter.check("key", rule, now=1))
    blocked = asyncio.run(limiter.check("key", rule, now=2))
    released = asyncio.run(limiter.check("key", rule, now=11))

    assert (first.allowed, first.remaining) == (True, 1)
    assert (second.allowed, second.remaining) == (True, 0)
    assert blocked.allowed is False
    assert blocked.retry_after == 8
    assert released.allowed is True


def test_rate_limit_identity_never_contains_raw_session_token() -> None:
    request = _request("/api/chat/send", cookie="sensitive-session-token")
    rule = RateLimitRule("generation", limit=20, window_seconds=60)

    key = rate_limit_key(request, rule)

    assert len(key) == 64
    assert "sensitive-session-token" not in key


def test_high_cost_routes_are_classified_independently() -> None:
    settings = Settings()

    assert classify_rate_limit(_request("/api/auth/register"), settings).name == "auth_register"
    assert classify_rate_limit(_request("/api/auth/login"), settings).name == "auth_login"
    assert (
        classify_rate_limit(_request("/api/auth/password-reset/request"), settings).name
        == "auth_email"
    )
    assert classify_rate_limit(_request("/api/providers/test"), settings).name == "provider_test"
    assert (
        classify_rate_limit(_request("/api/auth/account", method="DELETE"), settings).name
        == "auth_account_delete"
    )
    assert classify_rate_limit(_request("/api/chat/stream"), settings).name == "generation"
    assert (
        classify_rate_limit(_request("/api/admin/quota/reset-all"), settings).name
        == "admin_quota_reset"
    )
    assert (
        classify_rate_limit(_request("/api/admin/quota/policy", method="PUT"), settings).name
        == "admin_quota_policy"
    )
    assert (
        classify_rate_limit(
            _request("/api/workspace/stories/x/branches/y/export", method="GET"),
            settings,
        ).name
        == "export"
    )


def test_http_rate_limit_returns_retry_headers_before_authentication() -> None:
    settings = _production_settings(rate_limit_provider_test_requests=2)
    client = TestClient(create_app(settings), base_url="https://app.example.com")
    headers = {"Origin": "https://app.example.com"}

    first = client.post("/api/providers/test", headers=headers, json={})
    second = client.post("/api/providers/test", headers=headers, json={})
    blocked = client.post("/api/providers/test", headers=headers, json={})

    assert first.status_code in {401, 403, 422}
    assert first.headers["X-RateLimit-Limit"] == "2"
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many requests"}
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.headers["X-Request-ID"]
