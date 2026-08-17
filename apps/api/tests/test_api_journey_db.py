from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from app.config import Settings, get_settings
from app.db.models import AuthCredential, GenerationRequest, Message, User
from app.db.session import AsyncSessionLocal, engine
from app.llm.router import LLMGateway
from app.main import create_app
from app.services.auth_service import hash_password


def _done_event(response_text: str) -> dict:
    events = []
    for block in response_text.split("\n\n"):
        lines = block.splitlines()
        event_type = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if event_type and data:
            events.append((event_type, json.loads(data)))
    return next(payload for event_type, payload in events if event_type == "done")


def test_authenticated_interactive_novel_api_journey(monkeypatch) -> None:
    async def scenario() -> None:
        marker = uuid4().hex
        email = f"api-journey-{marker}@example.invalid"
        password = f"journey-{marker}-passphrase"
        user_id = None
        settings = Settings(app_environment="test", dry_run_llm=True, rate_limit_enabled=False)
        application = create_app(settings, database_engine=engine)
        application.dependency_overrides[get_settings] = lambda: settings

        try:
            async with AsyncSessionLocal() as session:
                user = User(
                    email=email,
                    display_name="Journey Player",
                    email_verified_at=datetime.now(timezone.utc),
                )
                session.add(user)
                await session.flush()
                user_id = user.id
                session.add(
                    AuthCredential(user_id=user.id, password_hash=hash_password(password))
                )
                await session.commit()

            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                follow_redirects=False,
            ) as client:
                login = await client.post(
                    "/api/auth/login",
                    json={"email": email, "password": password, "device_name": "CI browser"},
                )
                assert login.status_code == 200, login.text
                assert login.json()["user"]["email_verified"] is True
                assert "witscraft_session" in client.cookies

                created = await client.post(
                    "/api/workspace/stories",
                    json={
                        "title": "The Clockwork Key",
                        "genre": "mystery",
                        "world_name": "The Archive",
                        "premise": "The player must recover a rewritten memory.",
                        "protagonist_name": "Mira",
                        "protagonist_role": "archive investigator",
                        "tone": "tense and concise",
                        "opening_mode": "custom",
                        "opening_text": "The archive clock stops as Mira touches the key.",
                        "interaction_mode": "open",
                    },
                )
                assert created.status_code == 200, created.text
                workspace = created.json()
                story_id = workspace["story_id"]
                main_branch_id = workspace["branch_id"]
                assert workspace["messages"][-1]["content"].startswith("The archive clock")

                generated = await client.post(
                    "/api/chat/send",
                    headers={"Idempotency-Key": f"journey-{marker}-send"},
                    json={
                        "message": "I turn the key and enter the sealed room.",
                        "story_id": story_id,
                        "branch_id": main_branch_id,
                        "branch_version": 0,
                        "idempotency_key": f"journey-{marker}-send",
                    },
                )
                assert generated.status_code == 200, generated.text
                first_reply = generated.json()
                assert first_reply["branch_version"] == 1
                assert first_reply["model_call"]["dry_run"] is True

                regenerated = await client.post(
                    "/api/chat/send",
                    headers={"Idempotency-Key": f"journey-{marker}-regenerate"},
                    json={
                        "message": "",
                        "story_id": story_id,
                        "branch_id": main_branch_id,
                        "branch_version": 1,
                        "command": "regenerate",
                        "target_message_id": first_reply["message_id"],
                        "idempotency_key": f"journey-{marker}-regenerate",
                    },
                )
                assert regenerated.status_code == 200, regenerated.text
                assert regenerated.json()["branch_version"] == 2

                streamed = await client.post(
                    "/api/chat/stream",
                    headers={"Idempotency-Key": f"journey-{marker}-stream"},
                    json={
                        "message": "I ask the archive who changed the past.",
                        "story_id": story_id,
                        "branch_id": main_branch_id,
                        "branch_version": 2,
                        "stream": True,
                        "idempotency_key": f"journey-{marker}-stream",
                    },
                )
                assert streamed.status_code == 200, streamed.text
                done = _done_event(streamed.text)
                assert done["response"]["branch_version"] == 3

                stream_waiting = asyncio.Event()
                never_finish = asyncio.Event()

                async def slow_stream(_gateway, _request):
                    yield "A stable checkpoint."
                    stream_waiting.set()
                    await never_finish.wait()

                monkeypatch.setattr(LLMGateway, "stream", slow_stream)
                cancelled_key = f"journey-{marker}-cancel"
                cancelled_request = asyncio.create_task(
                    client.post(
                        "/api/chat/stream",
                        headers={"Idempotency-Key": cancelled_key},
                        json={
                            "message": "I stop before opening the final door.",
                            "story_id": story_id,
                            "branch_id": main_branch_id,
                            "branch_version": 3,
                            "stream": True,
                            "idempotency_key": cancelled_key,
                        },
                    )
                )
                await asyncio.wait_for(stream_waiting.wait(), timeout=2)
                cancelled_request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await cancelled_request

                async with AsyncSessionLocal() as verification:
                    cancelled_generation = await verification.scalar(
                        select(GenerationRequest).where(
                            GenerationRequest.user_id == user_id,
                            GenerationRequest.idempotency_key == cancelled_key,
                        )
                    )
                    assert cancelled_generation is not None
                    assert cancelled_generation.status == "cancelled"
                    partial = await verification.scalar(
                        select(Message)
                        .where(
                            Message.story_id == story_id,
                            Message.branch_id == main_branch_id,
                            Message.role == "assistant",
                        )
                        .order_by(Message.created_at.desc(), Message.id.desc())
                    )
                    assert partial is not None
                    assert partial.meta["partial"] is True
                    assert partial.content
                    assert "A stable checkpoint.".startswith(partial.content)

                branched = await client.post(
                    f"/api/workspace/stories/{story_id}/branches",
                    json={"name": "Refuse the archive"},
                )
                assert branched.status_code == 200, branched.text
                branch_workspace = branched.json()
                new_branch_id = branch_workspace["branch_id"]
                assert new_branch_id != main_branch_id
                assert len(branch_workspace["branches"]) == 2

                switched = await client.patch(
                    f"/api/workspace/stories/{story_id}/branches/{main_branch_id}/activate"
                )
                assert switched.status_code == 200, switched.text
                assert switched.json()["branch_id"] == main_branch_id

                exported = await client.get(
                    f"/api/workspace/stories/{story_id}/branches/{main_branch_id}/export",
                    params={"format": "json"},
                )
                assert exported.status_code == 200, exported.text
                assert exported.headers["content-type"].startswith("application/json")
                export_payload = exported.json()
                assert export_payload["story"]["title"] == "The Clockwork Key"
                assert any(message["role"] == "assistant" for message in export_payload["messages"])
        finally:
            application.dependency_overrides.clear()
            if user_id is not None:
                async with AsyncSessionLocal() as cleanup:
                    await cleanup.execute(delete(User).where(User.id == user_id))
                    await cleanup.commit()
            await engine.dispose()

    asyncio.run(scenario())
