from __future__ import annotations

import base64
import hashlib
import hmac
import math
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthActionToken, AuthCredential, AuthLoginThrottle, AuthSession, User


SESSION_COOKIE_NAME = "witscraft_session"
EMAIL_VERIFICATION_PURPOSE = "email_verification"
PASSWORD_RESET_PURPOSE = "password_reset"
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LENGTH = 64


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 255 or not _EMAIL_PATTERN.fullmatch(email):
        raise ValueError("Enter a valid email address")
    return email


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_LENGTH,
    )
    return "$".join(
        [
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            _encode_bytes(salt),
            _encode_bytes(digest),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_decode_bytes(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_decode_bytes(expected)),
        )
        return hmac.compare_digest(digest, _decode_bytes(expected))
    except (TypeError, ValueError):
        return False


async def find_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(
        select(User).where(func.lower(User.email) == normalize_email(email)).limit(1)
    )
    return result.scalar_one_or_none()


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    normalized = normalize_email(email)
    result = await session.execute(
        select(User, AuthCredential)
        .join(AuthCredential, AuthCredential.user_id == User.id)
        .where(func.lower(User.email) == normalized)
        .limit(1)
    )
    row = result.one_or_none()
    if row is None:
        return None
    user, credential = row
    return user if verify_password(password, credential.password_hash) else None


async def create_registered_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
    legacy_user_id: str | None,
) -> tuple[User, bool]:
    normalized = normalize_email(email)
    if await find_user_by_email(session, normalized) is not None:
        raise ValueError("An account already exists for this email")

    user = await _claimable_legacy_user(session, legacy_user_id)
    claimed_legacy_workspace = user is not None
    if user is None:
        user = User(id=uuid4(), email=normalized, display_name=display_name.strip())
        session.add(user)
        await session.flush()
    else:
        user.email = normalized
        user.display_name = display_name.strip()
    user.email_verified_at = None

    session.add(AuthCredential(user_id=user.id, password_hash=hash_password(password)))
    await session.flush()
    return user, claimed_legacy_workspace


async def create_auth_session(
    session: AsyncSession,
    user_id: UUID,
    *,
    session_days: int,
    device_name: str | None = None,
    ip_address: str | None = None,
    ip_region: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, datetime]:
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=session_days)
    normalized_device = (device_name or "").strip()[:160] or None
    normalized_ip = (ip_address or "").strip()[:64] or None
    if normalized_device and normalized_ip:
        await session.execute(
            delete(AuthSession).where(
                AuthSession.user_id == user_id,
                AuthSession.device_name == normalized_device,
                AuthSession.ip_address == normalized_ip,
            )
        )
    session.add(
        AuthSession(
            user_id=user_id,
            token_hash=hash_session_token(raw_token),
            device_name=normalized_device,
            ip_address=normalized_ip,
            ip_region=(ip_region or "").strip()[:160] or None,
            user_agent=(user_agent or "").strip()[:500] or None,
            expires_at=expires_at,
        )
    )
    await session.flush()
    return raw_token, expires_at


async def revoke_auth_session(session: AsyncSession, raw_token: str | None) -> None:
    if not raw_token:
        return
    await session.execute(
        delete(AuthSession).where(AuthSession.token_hash == hash_session_token(raw_token))
    )


async def issue_action_token(
    session: AsyncSession,
    user_id: UUID,
    *,
    purpose: str,
    lifetime: timedelta,
    min_interval_seconds: int,
) -> str | None:
    now = datetime.now(timezone.utc)
    latest_result = await session.execute(
        select(AuthActionToken.created_at)
        .where(AuthActionToken.user_id == user_id, AuthActionToken.purpose == purpose)
        .order_by(AuthActionToken.created_at.desc())
        .limit(1)
    )
    latest_created_at = latest_result.scalar_one_or_none()
    if (
        latest_created_at is not None
        and (now - latest_created_at).total_seconds() < min_interval_seconds
    ):
        return None

    await session.execute(
        delete(AuthActionToken).where(
            AuthActionToken.user_id == user_id,
            AuthActionToken.purpose == purpose,
        )
    )
    raw_token = secrets.token_urlsafe(32)
    session.add(
        AuthActionToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=hash_action_token(raw_token),
            expires_at=now + lifetime,
        )
    )
    await session.flush()
    return raw_token


async def verify_email_token(session: AsyncSession, raw_token: str) -> User | None:
    token = await _consume_action_token(session, raw_token, EMAIL_VERIFICATION_PURPOSE)
    if token is None:
        return None
    user = await session.get(User, token.user_id)
    if user is None:
        return None
    user.email_verified_at = datetime.now(timezone.utc)
    await session.flush()
    return user


async def reset_password_with_token(
    session: AsyncSession,
    raw_token: str,
    new_password: str,
) -> User | None:
    token = await _consume_action_token(session, raw_token, PASSWORD_RESET_PURPOSE)
    if token is None:
        return None
    user = await session.get(User, token.user_id)
    credential_result = await session.execute(
        select(AuthCredential).where(AuthCredential.user_id == token.user_id).limit(1)
    )
    credential = credential_result.scalar_one_or_none()
    if user is None or credential is None:
        return None
    credential.password_hash = hash_password(new_password)
    await session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    await session.flush()
    return user


def make_login_throttle_key(email: str, client_host: str) -> str:
    identifier = email.strip().lower()
    return hashlib.sha256(f"{client_host}|{identifier}".encode("utf-8")).hexdigest()


async def get_login_retry_after(session: AsyncSession, key_hash: str) -> int | None:
    throttle = await session.get(AuthLoginThrottle, key_hash)
    if throttle is None or throttle.locked_until is None:
        return None
    remaining = (throttle.locked_until - datetime.now(timezone.utc)).total_seconds()
    return max(1, math.ceil(remaining)) if remaining > 0 else None


async def record_failed_login(
    session: AsyncSession,
    key_hash: str,
    *,
    max_attempts: int,
    window_minutes: int,
    lock_minutes: int,
) -> int | None:
    now = datetime.now(timezone.utc)
    await session.execute(
        pg_insert(AuthLoginThrottle)
        .values(
            key_hash=key_hash,
            failure_count=0,
            window_started_at=now,
            locked_until=None,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[AuthLoginThrottle.key_hash])
    )
    result = await session.execute(
        select(AuthLoginThrottle)
        .where(AuthLoginThrottle.key_hash == key_hash)
        .with_for_update()
    )
    throttle = result.scalar_one()
    window = timedelta(minutes=window_minutes)
    if now - throttle.window_started_at >= window:
        throttle.failure_count = 0
        throttle.window_started_at = now
        throttle.locked_until = None
    elif throttle.locked_until is not None and throttle.locked_until <= now:
        throttle.failure_count = 0
        throttle.window_started_at = now
        throttle.locked_until = None

    throttle.failure_count += 1
    throttle.updated_at = now
    if throttle.failure_count >= max_attempts:
        throttle.locked_until = now + timedelta(minutes=lock_minutes)
    await session.flush()
    return await get_login_retry_after(session, key_hash)


async def clear_login_throttle(session: AsyncSession, key_hash: str) -> None:
    await session.execute(
        delete(AuthLoginThrottle).where(AuthLoginThrottle.key_hash == key_hash)
    )


async def prune_login_throttles(session: AsyncSession, retention_hours: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
    await session.execute(
        delete(AuthLoginThrottle).where(AuthLoginThrottle.updated_at < cutoff)
    )


def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def hash_action_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def _consume_action_token(
    session: AsyncSession,
    raw_token: str,
    purpose: str,
) -> AuthActionToken | None:
    result = await session.execute(
        select(AuthActionToken)
        .where(
            AuthActionToken.token_hash == hash_action_token(raw_token),
            AuthActionToken.purpose == purpose,
            AuthActionToken.used_at.is_(None),
            AuthActionToken.expires_at > datetime.now(timezone.utc),
        )
        .with_for_update()
        .limit(1)
    )
    token = result.scalar_one_or_none()
    if token is None:
        return None
    token.used_at = datetime.now(timezone.utc)
    await session.flush()
    return token


async def _claimable_legacy_user(session: AsyncSession, legacy_user_id: str | None) -> User | None:
    if not legacy_user_id:
        return None
    try:
        user_id = UUID(legacy_user_id)
    except ValueError:
        return None

    user = await session.get(User, user_id)
    if user is None or user.email != f"{user.id}@local.witscraft.dev":
        return None
    credential_result = await session.execute(
        select(AuthCredential.id).where(AuthCredential.user_id == user.id).limit(1)
    )
    return None if credential_result.scalar_one_or_none() is not None else user


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
