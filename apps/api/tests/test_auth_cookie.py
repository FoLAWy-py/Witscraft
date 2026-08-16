import pytest
from fastapi import Response
from pydantic import ValidationError

from app.config import Settings
from app.routers.auth import _delete_session_cookie, _set_session_cookie


def test_development_cookie_remains_usable_over_local_http() -> None:
    settings = Settings(
        app_environment="development",
        frontend_base_url="http://127.0.0.1:3000",
    )
    response = Response()

    _set_session_cookie(response, "test-token", settings)

    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie


def test_production_cookie_is_secure_by_default() -> None:
    settings = Settings(
        app_environment="production",
        frontend_base_url="https://app.example.com",
    )
    response = Response()

    _set_session_cookie(response, "test-token", settings)

    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


def test_production_rejects_http_frontend_and_insecure_override() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(app_environment="production", frontend_base_url="http://app.example.com")

    with pytest.raises(ValidationError, match="cannot be disabled"):
        Settings(
            app_environment="production",
            frontend_base_url="https://app.example.com",
            auth_cookie_secure=False,
        )


def test_cookie_deletion_uses_the_same_secure_attributes() -> None:
    settings = Settings(
        app_environment="production",
        frontend_base_url="https://app.example.com",
    )
    response = Response()

    _delete_session_cookie(response, settings)

    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
