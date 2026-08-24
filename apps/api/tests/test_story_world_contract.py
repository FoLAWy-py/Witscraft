import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import Settings
from app.routers.workspace import create_story, create_world, set_story_world
from app.schemas.chat import CreateStoryRequest, SetStoryWorldRequest, UpdateWorldRequest


def test_story_world_cannot_be_replaced_or_switched() -> None:
    async def scenario() -> None:
        user_id = uuid4()

        with pytest.raises(HTTPException) as reuse_error:
            await create_story(
                CreateStoryRequest(
                    title="Separate novel",
                    world_id=str(uuid4()),
                    genre="mystery",
                    world_name="Own world",
                    premise="A sealed archive opens at midnight.",
                    protagonist_name="Mara",
                    protagonist_role="Archivist",
                    tone="restrained",
                ),
                Request({"type": "http", "method": "POST", "path": "/"}),
                settings=Settings(app_environment="test"),
                session=None,  # type: ignore[arg-type]
                user_id=user_id,
            )
        assert reuse_error.value.status_code == 422
        assert "cannot be reused" in str(reuse_error.value.detail)

        with pytest.raises(HTTPException) as create_error:
            await create_world(
                UpdateWorldRequest(name="Replacement"),
                active_story_id=str(uuid4()),
                session=None,  # type: ignore[arg-type]
                user_id=user_id,
            )
        assert create_error.value.status_code == 409
        assert "one world" in str(create_error.value.detail)

        with pytest.raises(HTTPException) as switch_error:
            await set_story_world(
                str(uuid4()),
                SetStoryWorldRequest(world_id=str(uuid4())),
                session=None,  # type: ignore[arg-type]
                user_id=user_id,
            )
        assert switch_error.value.status_code == 409
        assert "cannot be switched" in str(switch_error.value.detail)

    asyncio.run(scenario())
