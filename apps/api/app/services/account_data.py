from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuthSession,
    CanonFact,
    Character,
    GenerationRequest,
    MemoryItem,
    Message,
    ModelCall,
    PlotEvent,
    Story,
    StoryBranch,
    StoryStateSnapshot,
    StorySummary,
    User,
    UserModelRoute,
    UserModelRouteChange,
    UserPreference,
    World,
)


async def build_account_export_payload(session: AsyncSession, user: User) -> dict[str, Any]:
    stories = await _rows(session, Story, Story.user_id == user.id)
    story_ids = [story.id for story in stories]
    branches = await _story_rows(session, StoryBranch, StoryBranch.story_id, story_ids)

    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "email_verified_at": _json_value(user.email_verified_at),
            "created_at": _json_value(user.created_at),
            "updated_at": _json_value(user.updated_at),
        },
        "sessions": [
            _serialize(row, exclude={"token_hash", "user_id"})
            for row in await _rows(session, AuthSession, AuthSession.user_id == user.id)
        ],
        "worlds": [
            _serialize(row, exclude={"user_id"})
            for row in await _rows(session, World, World.user_id == user.id)
        ],
        "characters": [
            _serialize(row, exclude={"user_id"})
            for row in await _rows(session, Character, Character.user_id == user.id)
        ],
        "stories": [_serialize(row, exclude={"user_id"}) for row in stories],
        "branches": [_serialize(row) for row in branches],
        "messages": [
            _serialize(row)
            for row in await _story_rows(session, Message, Message.story_id, story_ids)
        ],
        "generation_requests": [
            _serialize(row, exclude={"user_id"})
            for row in await _rows(session, GenerationRequest, GenerationRequest.user_id == user.id)
        ],
        "plot_events": [
            _serialize(row)
            for row in await _story_rows(session, PlotEvent, PlotEvent.story_id, story_ids)
        ],
        "state_snapshots": [
            _serialize(row)
            for row in await _story_rows(
                session,
                StoryStateSnapshot,
                StoryStateSnapshot.story_id,
                story_ids,
            )
        ],
        "summaries": [
            _serialize(row, exclude={"user_id"})
            for row in await _rows(session, StorySummary, StorySummary.user_id == user.id)
        ],
        "canon_facts": [
            _serialize(row)
            for row in await _story_rows(session, CanonFact, CanonFact.story_id, story_ids)
        ],
        "memories": [
            _serialize(row, exclude={"user_id", "embedding"})
            for row in await _memory_rows(session, user.id, story_ids)
        ],
        "preferences": [
            _serialize(row, exclude={"user_id"})
            for row in await _rows(session, UserPreference, UserPreference.user_id == user.id)
        ],
        "model_routes": [
            _serialize(row, exclude={"user_id"})
            for row in await _rows(session, UserModelRoute, UserModelRoute.user_id == user.id)
        ],
        "model_route_changes": [
            _serialize(row, exclude={"user_id", "sequence"})
            for row in await _rows(
                session,
                UserModelRouteChange,
                UserModelRouteChange.user_id == user.id,
            )
        ],
        "model_calls": [
            _serialize(row, exclude={"user_id"})
            for row in await _rows(session, ModelCall, ModelCall.user_id == user.id)
        ],
    }


async def _rows(session: AsyncSession, model, *conditions) -> list[Any]:
    statement = select(model).where(*conditions)
    if hasattr(model, "created_at"):
        statement = statement.order_by(model.created_at.asc())
    return list((await session.execute(statement)).scalars().all())


async def _story_rows(session, model, story_column, story_ids: list[UUID]) -> list[Any]:
    if not story_ids:
        return []
    return await _rows(session, model, story_column.in_(story_ids))


async def _memory_rows(
    session: AsyncSession,
    user_id: UUID,
    story_ids: list[UUID],
) -> list[MemoryItem]:
    conditions = [MemoryItem.user_id == user_id]
    if story_ids:
        conditions.append(MemoryItem.story_id.in_(story_ids))
    return await _rows(session, MemoryItem, or_(*conditions))


def _serialize(row: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    excluded = exclude or set()
    return {
        attribute.key: _json_value(getattr(row, attribute.key))
        for attribute in inspect(type(row)).column_attrs
        if attribute.key not in excluded
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
