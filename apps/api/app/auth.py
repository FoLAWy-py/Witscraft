from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthSession, User
from app.db.session import get_session
from app.services.auth_service import SESSION_COOKIE_NAME, hash_session_token


async def get_current_user_id(
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    session: AsyncSession = Depends(get_session),
) -> UUID:
    if not session_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    result = await session.execute(
        select(AuthSession.user_id)
        .where(
            AuthSession.token_hash == hash_session_token(session_token),
            AuthSession.expires_at > datetime.now(timezone.utc),
        )
        .limit(1)
    )
    user_id = result.scalar_one_or_none()
    if user_id is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return user_id


async def get_verified_user_id(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> UUID:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.email_verified_at is None:
        raise HTTPException(status_code=403, detail="Email verification required")
    return user_id


async def get_admin_user(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user
