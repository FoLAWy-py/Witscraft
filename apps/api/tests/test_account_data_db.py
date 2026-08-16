import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import delete, func, select
from starlette.requests import Request

from app.config import Settings
from app.db.models import (
    AuthCredential,
    AuthSession,
    Character,
    MemoryItem,
    Message,
    ModelCall,
    Story,
    StoryBranch,
    User,
    UserModelRoute,
    UserPreference,
    World,
)
from app.db.session import AsyncSessionLocal, engine
from app.routers.auth import delete_account
from app.schemas.auth import AccountDeletionRequest
from app.services.account_data import build_account_export_payload
from app.services.auth_service import hash_password, hash_session_token


def test_account_export_and_deletion_lifecycle() -> None:
    async def scenario() -> None:
        marker = uuid4().hex
        password = "correct horse battery staple"
        user_id = None
        control_id = None
        try:
            async with AsyncSessionLocal() as session:
                user = User(
                    email=f"account-lifecycle-{marker}@example.invalid",
                    display_name="Lifecycle Author",
                    email_verified_at=datetime.now(timezone.utc),
                )
                control = User(
                    email=f"account-control-{marker}@example.invalid",
                    display_name="Control Author",
                    email_verified_at=datetime.now(timezone.utc),
                )
                session.add_all([user, control])
                await session.flush()
                user_id = user.id
                control_id = control.id
                session.add_all(
                    [
                        AuthCredential(user_id=user.id, password_hash=hash_password(password)),
                        AuthSession(
                            user_id=user.id,
                            token_hash=hash_session_token("private-session-token"),
                            device_name="Test browser",
                            ip_address="192.0.2.10",
                            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                        ),
                    ]
                )
                world = World(
                    user_id=user.id,
                    name="Private world",
                    rules={},
                    lorebook=[],
                    tone={},
                )
                session.add(world)
                await session.flush()
                character = Character(
                    user_id=user.id,
                    world_id=world.id,
                    name="Private character",
                    persona={},
                    speaking_style={},
                    relationship_to_user={},
                    constraints={},
                )
                story = Story(user_id=user.id, world_id=world.id, title="Private story")
                session.add_all([character, story])
                await session.flush()
                branch = StoryBranch(story_id=story.id, name="main")
                session.add(branch)
                await session.flush()
                story.current_branch_id = branch.id
                session.add_all(
                    [
                        Message(
                            story_id=story.id,
                            branch_id=branch.id,
                            role="user",
                            content="Private story message",
                            meta={},
                        ),
                        MemoryItem(
                            user_id=user.id,
                            story_id=story.id,
                            branch_id=branch.id,
                            memory_type="long_term",
                            content="Private memory",
                            entity_tags=[],
                            meta={},
                            embedding=[0.123456, 0.654321],
                        ),
                        UserPreference(
                            user_id=user.id,
                            preference_type="style",
                            content="Private preference",
                        ),
                        UserModelRoute(
                            user_id=user.id,
                            purpose="normal_chat",
                            provider="deepinfra",
                            model="Qwen/Qwen3-Max",
                        ),
                        ModelCall(
                            user_id=user.id,
                            story_id=story.id,
                            call_type="llm",
                            provider="deepinfra",
                            model="Qwen/Qwen3-Max",
                            purpose="normal_chat",
                            status="succeeded",
                            request={"message_count": 1},
                            response={"output_characters": 20},
                        ),
                    ]
                )
                await session.commit()

                export = await build_account_export_payload(session, user)
                encoded = json.dumps(export)
                assert export["account"]["email"] == user.email
                assert export["stories"][0]["title"] == "Private story"
                assert export["messages"][0]["content"] == "Private story message"
                assert export["memories"][0]["content"] == "Private memory"
                assert "password_hash" not in encoded
                assert "token_hash" not in encoded
                assert "private-session-token" not in encoded
                assert "0.123456" not in encoded

                response = Response()
                request = Request(
                    {
                        "type": "http",
                        "method": "DELETE",
                        "path": "/api/auth/account",
                        "headers": [],
                        "query_string": b"",
                        "client": ("192.0.2.10", 443),
                        "server": ("testserver", 443),
                    }
                )
                with pytest.raises(HTTPException) as wrong_password:
                    await delete_account(
                        AccountDeletionRequest(password="wrong-password", confirmation="DELETE"),
                        request,
                        Response(),
                        user.id,
                        session,
                        Settings(),
                    )
                assert wrong_password.value.status_code == 401
                assert await session.get(User, user.id) is not None

                await delete_account(
                    AccountDeletionRequest(password=password, confirmation="DELETE"),
                    request,
                    response,
                    user.id,
                    session,
                    Settings(),
                )
                assert "witscraft_session=" in response.headers["set-cookie"]

            async with AsyncSessionLocal() as verification:
                assert await verification.get(User, user_id) is None
                assert await verification.get(User, control_id) is not None
                for model, owner_column in (
                    (AuthCredential, AuthCredential.user_id),
                    (AuthSession, AuthSession.user_id),
                    (World, World.user_id),
                    (Character, Character.user_id),
                    (Story, Story.user_id),
                    (MemoryItem, MemoryItem.user_id),
                    (UserPreference, UserPreference.user_id),
                    (UserModelRoute, UserModelRoute.user_id),
                    (ModelCall, ModelCall.user_id),
                ):
                    count = await verification.scalar(
                        select(func.count()).select_from(model).where(owner_column == user_id)
                    )
                    assert count == 0, model.__tablename__
        finally:
            if control_id is not None:
                async with AsyncSessionLocal() as cleanup:
                    await cleanup.execute(delete(User).where(User.id == control_id))
                    if user_id is not None:
                        await cleanup.execute(delete(User).where(User.id == user_id))
                    await cleanup.commit()
            await engine.dispose()

    asyncio.run(scenario())
