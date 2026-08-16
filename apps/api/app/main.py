import re
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings, get_settings, validate_runtime_security
from app.logging_security import install_sensitive_log_filters
from app.routers import auth, chat, providers, workspace
from app.services.auth_service import SESSION_COOKIE_NAME
from app.services.rate_limiter import (
    SlidingWindowRateLimiter,
    classify_rate_limit,
    rate_limit_key,
)


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _origin_allowed(settings: Settings, origin: str) -> bool:
    allowed = {settings.frontend_origin, *settings.cors_origins, *settings.csrf_trusted_origins}
    if origin in allowed:
        return True
    return bool(settings.cors_origin_regex and re.fullmatch(settings.cors_origin_regex, origin))


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    validate_runtime_security(app_settings)
    install_sensitive_log_filters()
    application = FastAPI(title=app_settings.app_name)
    rate_limiter = SlidingWindowRateLimiter(app_settings.rate_limit_max_keys)

    @application.middleware("http")
    async def csrf_origin_middleware(request: Request, call_next):
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("Origin")
            if origin and not _origin_allowed(app_settings, origin):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-site request blocked"},
                )
            if (
                not origin
                and request.cookies.get(SESSION_COOKIE_NAME)
                and request.headers.get("Sec-Fetch-Site") == "cross-site"
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-site request blocked"},
                )
        return await call_next(request)

    @application.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        rule = classify_rate_limit(request, app_settings) if app_settings.rate_limits_active else None
        if rule is None:
            return await call_next(request)
        decision = await rate_limiter.check(rate_limit_key(request, rule), rule)
        headers = {
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(decision.remaining),
            "X-RateLimit-Reset": str(decision.reset_after),
        }
        if not decision.allowed:
            headers["Retry-After"] = str(decision.retry_after)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers=headers,
            )
        response = await call_next(request)
        response.headers.update(headers)
        return response

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "").strip()
        normalized = supplied.replace("-", "").replace("_", "")
        request_id = (
            supplied
            if supplied and len(supplied) <= 64 and normalized.isalnum()
            else uuid4().hex
        )
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @application.exception_handler(SQLAlchemyError)
    async def database_handler(_request: Request, _error: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "Database temporarily unavailable"},
        )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_origin_regex=app_settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID"],
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=app_settings.allowed_hosts,
    )

    application.include_router(chat.router, prefix=app_settings.api_prefix)
    application.include_router(providers.router, prefix=app_settings.api_prefix)
    application.include_router(workspace.router, prefix=app_settings.api_prefix)
    application.include_router(auth.router, prefix=app_settings.api_prefix)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "app": app_settings.app_name}

    return application


app = create_app()


async def database_error_handler(request: Request, error: SQLAlchemyError) -> JSONResponse:
    handler = app.exception_handlers[SQLAlchemyError]
    return await handler(request, error)
