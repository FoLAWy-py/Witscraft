from datetime import datetime, timedelta, timezone
import ipaddress
import json
import re
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.config import Settings, get_settings
from app.db.models import AuthLoginThrottle, AuthSession, ModelCall, Story, User
from app.db.session import get_session
from app.schemas.auth import (
    AuthResponse,
    AccountDeletionRequest,
    AuthSessionListResponse,
    AuthSessionResponse,
    AuthUserResponse,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RegisterRequest,
    TokenRequest,
)
from app.services.auth_service import (
    EMAIL_VERIFICATION_PURPOSE,
    PASSWORD_RESET_PURPOSE,
    SESSION_COOKIE_NAME,
    authenticate_user,
    clear_login_throttle,
    create_auth_session,
    create_registered_user,
    find_user_by_email,
    get_login_retry_after,
    hash_session_token,
    issue_action_token,
    make_login_throttle_key,
    normalize_email,
    prune_login_throttles,
    record_failed_login,
    reset_password_with_token,
    revoke_auth_session,
    verify_email_token,
)
from app.services.account_data import build_account_export_payload
from app.services.email_service import (
    EmailDeliveryError,
    check_smtp_connection,
    send_password_reset_email,
    send_verification_email,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _client_region(request: Request, address: str) -> str:
    city = next(
        (request.headers.get(name) for name in ("cf-ipcity", "x-vercel-ip-city", "x-geo-city") if request.headers.get(name)),
        None,
    )
    country = next(
        (request.headers.get(name) for name in ("cf-ipcountry", "x-vercel-ip-country", "x-country-code", "x-geo-country") if request.headers.get(name)),
        None,
    )
    if city or country:
        return " · ".join(unquote(value) for value in (city, country) if value)[:160]
    try:
        parsed = ipaddress.ip_address(address)
        if parsed.is_private or parsed.is_loopback:
            return "局域网"
    except ValueError:
        pass
    return "地区未知"


def _fallback_device_name(request: Request) -> str:
    user_agent = request.headers.get("user-agent", "")
    browser = "Chrome" if "Chrome/" in user_agent or "CriOS/" in user_agent else "Safari" if "Safari/" in user_agent else "Browser"
    if "iPhone" in user_agent:
        device = "iPhone"
    elif "iPad" in user_agent:
        device = "iPad"
    elif "Android" in user_agent:
        match = re.search(r"Android[^;]*;\s*([^;)]+)", user_agent)
        device = match.group(1).replace(" Build/", " ").strip() if match else "Android"
    elif "Macintosh" in user_agent:
        device = "Mac"
    elif "Windows" in user_agent:
        device = "Windows PC"
    else:
        device = "未知设备"
    return f"{device} · {browser}"


def _session_metadata(request: Request, supplied_device_name: str | None = None) -> dict[str, str]:
    address = _client_ip(request)
    return {
        "device_name": (supplied_device_name or "").strip() or _fallback_device_name(request),
        "ip_address": address,
        "ip_region": _client_region(request, address),
        "user_agent": request.headers.get("user-agent", ""),
    }


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    response: Response,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    await _require_smtp_ready(settings)
    try:
        user, _claimed_legacy_workspace = await create_registered_user(
            session,
            email=request.email,
            password=request.password,
            display_name=request.display_name,
            legacy_user_id=request.legacy_user_id,
        )
        token, _ = await create_auth_session(
            session,
            user.id,
            session_days=settings.auth_session_days,
            **_session_metadata(http_request, request.device_name),
        )
        verification_token = await issue_action_token(
            session,
            user.id,
            purpose=EMAIL_VERIFICATION_PURPOSE,
            lifetime=timedelta(hours=settings.auth_verification_token_hours),
            min_interval_seconds=0,
        )
        if verification_token is None:
            raise RuntimeError("Registration verification token was not created")
        await send_verification_email(
            settings,
            recipient=user.email,
            display_name=user.display_name or "Player",
            token=verification_token,
        )
        await session.commit()
    except ValueError as error:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail="An account already exists for this email") from error
    except EmailDeliveryError as error:
        await session.rollback()
        raise HTTPException(status_code=503, detail="Email delivery is temporarily unavailable") from error

    _set_session_cookie(response, token, settings)
    return AuthResponse(user=_user_response(user))


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    client_host = _client_ip(request)
    throttle_key = make_login_throttle_key(payload.email, client_host)
    try:
        normalize_email(payload.email)
    except ValueError as error:
        raise HTTPException(status_code=401, detail="Invalid email or password") from error

    await prune_login_throttles(session, settings.auth_login_throttle_retention_hours)
    retry_after = await get_login_retry_after(session, throttle_key)
    if retry_after is not None:
        await session.commit()
        raise _login_throttled(retry_after)

    user = await authenticate_user(session, payload.email, payload.password)
    if user is None:
        retry_after = await record_failed_login(
            session,
            throttle_key,
            max_attempts=settings.auth_login_max_attempts,
            window_minutes=settings.auth_login_window_minutes,
            lock_minutes=settings.auth_login_lock_minutes,
        )
        await session.commit()
        if retry_after is not None:
            raise _login_throttled(retry_after)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await clear_login_throttle(session, throttle_key)
    token, _ = await create_auth_session(
        session,
        user.id,
        session_days=settings.auth_session_days,
        **_session_metadata(request, payload.device_name),
    )
    await session.commit()
    _set_session_cookie(response, token, settings)
    return AuthResponse(user=_user_response(user))


@router.post(
    "/email-verification/request",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_email_verification(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    await _require_smtp_ready(settings)
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.email_verified_at is not None:
        return MessageResponse(message="Email is already verified")
    token = await issue_action_token(
        session,
        user.id,
        purpose=EMAIL_VERIFICATION_PURPOSE,
        lifetime=timedelta(hours=settings.auth_verification_token_hours),
        min_interval_seconds=settings.auth_email_min_interval_seconds,
    )
    if token is None:
        await session.rollback()
        raise HTTPException(
            status_code=429,
            detail="Verification email was sent recently. Try again shortly.",
            headers={"Retry-After": str(settings.auth_email_min_interval_seconds)},
        )
    try:
        await send_verification_email(
            settings,
            recipient=user.email,
            display_name=user.display_name or "Player",
            token=token,
        )
        await session.commit()
    except EmailDeliveryError as error:
        await session.rollback()
        raise HTTPException(status_code=503, detail="Email delivery is temporarily unavailable") from error
    return MessageResponse(message="Verification email sent")


@router.post("/email-verification/confirm", response_model=AuthResponse)
async def confirm_email_verification(
    payload: TokenRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    user = await verify_email_token(session, payload.token)
    if user is None:
        raise HTTPException(status_code=400, detail="Verification link is invalid or expired")
    await session.commit()
    return AuthResponse(user=_user_response(user))


@router.post(
    "/password-reset/request",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_password_reset(
    payload: PasswordResetRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    await _require_smtp_ready(settings)
    generic_message = "If the account exists, a password reset email has been sent"
    try:
        user = await find_user_by_email(session, payload.email)
    except ValueError:
        return MessageResponse(message=generic_message)
    if user is None:
        return MessageResponse(message=generic_message)
    token = await issue_action_token(
        session,
        user.id,
        purpose=PASSWORD_RESET_PURPOSE,
        lifetime=timedelta(minutes=settings.auth_password_reset_token_minutes),
        min_interval_seconds=settings.auth_email_min_interval_seconds,
    )
    if token is not None:
        try:
            await send_password_reset_email(
                settings,
                recipient=user.email,
                display_name=user.display_name or "Player",
                token=token,
            )
            await session.commit()
        except EmailDeliveryError as error:
            await session.rollback()
            raise HTTPException(status_code=503, detail="Email delivery is temporarily unavailable") from error
    return MessageResponse(message=generic_message)


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    user = await reset_password_with_token(session, payload.token, payload.new_password)
    if user is None:
        raise HTTPException(status_code=400, detail="Password reset link is invalid or expired")
    await session.commit()
    _delete_session_cookie(response, settings)
    return MessageResponse(message="Password reset complete. Sign in with your new password.")


@router.get("/sessions", response_model=AuthSessionListResponse)
async def list_sessions(
    request: Request,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> AuthSessionListResponse:
    current_hash = hash_session_token(session_token or "")
    current_result = await session.execute(
        select(AuthSession).where(AuthSession.token_hash == current_hash)
    )
    current_session = current_result.scalar_one_or_none()
    if current_session is not None:
        metadata = _session_metadata(request)
        for key, value in metadata.items():
            setattr(current_session, key, value)
        await session.commit()
    result = await session.execute(
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.expires_at > datetime.now(timezone.utc),
        )
        .order_by(AuthSession.created_at.desc())
    )
    return AuthSessionListResponse(
        sessions=[
            AuthSessionResponse(
                id=str(auth_session.id),
                created_at=auth_session.created_at,
                expires_at=auth_session.expires_at,
                current=auth_session.token_hash == current_hash,
                device_name=auth_session.device_name,
                ip_address=auth_session.ip_address,
                ip_region=auth_session.ip_region,
            )
            for auth_session in result.scalars().all()
        ]
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    response: Response,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    auth_session = await session.get(AuthSession, session_id)
    if auth_session is None or auth_session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    is_current = auth_session.token_hash == hash_session_token(session_token or "")
    await session.delete(auth_session)
    await session.commit()
    if is_current:
        _delete_session_cookie(response, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    await revoke_auth_session(session, session_token)
    await session.commit()
    _delete_session_cookie(response, settings)


@router.get("/export")
async def export_account(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = await build_account_export_payload(session, user)
    filename = f"witscraft-account-{datetime.now(timezone.utc):%Y%m%d}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    payload: AccountDeletionRequest,
    request: Request,
    response: Response,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    authenticated = await authenticate_user(session, user.email, payload.password)
    if authenticated is None or authenticated.id != user_id:
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    story_ids = list(
        (await session.execute(select(Story.id).where(Story.user_id == user_id))).scalars()
    )
    model_call_owner = ModelCall.user_id == user_id
    if story_ids:
        model_call_owner = or_(model_call_owner, ModelCall.story_id.in_(story_ids))
    await session.execute(delete(ModelCall).where(model_call_owner))
    await session.execute(
        delete(AuthLoginThrottle).where(
            AuthLoginThrottle.key_hash == make_login_throttle_key(user.email, _client_ip(request))
        )
    )
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()
    _delete_session_cookie(response, settings)


@router.get("/me", response_model=AuthResponse)
async def me(
    request: Request,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    current_hash = hash_session_token(session_token or "")
    current_result = await session.execute(
        select(AuthSession).where(AuthSession.token_hash == current_hash)
    )
    current_session = current_result.scalar_one_or_none()
    if current_session is not None and current_session.user_id == user_id:
        metadata = _session_metadata(request)
        for key, value in metadata.items():
            setattr(current_session, key, value)
        await session.commit()
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return AuthResponse(user=_user_response(user))


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.auth_session_days * 24 * 60 * 60,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _delete_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _login_throttled(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many login attempts. Try again later.",
        headers={"Retry-After": str(retry_after)},
    )


async def _require_smtp_ready(settings: Settings) -> None:
    if not settings.smtp_configured:
        raise HTTPException(status_code=503, detail="Email delivery is not configured")
    try:
        await check_smtp_connection(settings)
    except EmailDeliveryError as error:
        raise HTTPException(status_code=503, detail="Email delivery is temporarily unavailable") from error


def _user_response(user: User) -> AuthUserResponse:
    return AuthUserResponse(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name or "Player",
        email_verified=user.email_verified_at is not None,
        is_admin=user.is_admin,
    )
