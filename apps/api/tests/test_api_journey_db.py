from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select

from app.config import Settings, get_settings
from app.db.models import (
    AuthCredential,
    GenerationRequest,
    Message,
    MemoryEmbeddingTask,
    ModelCall,
    Story,
    StoryChapter,
    StyleProfile,
    User,
    UserModelRoute,
    World,
)
from app.db.session import AsyncSessionLocal, engine
from app.llm.router import LLMGateway
from app.schemas.llm import LLMResponse
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
                session.add(
                    UserModelRoute(
                        user_id=user.id,
                        purpose="normal_chat",
                        provider="deepinfra",
                        model="zai-org/GLM-5.2",
                    )
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

                reference_text = "\n".join(
                    f"段落{index}描写潮汐、石阶与灯影，句式各有停顿，但不替主角决定行动。"
                    for index in range(1, 55)
                )
                profiled = await client.post(
                    "/api/workspace/style-profiles",
                    json={
                        "name": "Journey abstract profile",
                        "source_type": "user_owned",
                        "source_label": "Integration fixture",
                        "language": "zh-CN",
                        "raw_text": reference_text,
                        "rights_attested": True,
                    },
                )
                assert profiled.status_code == 200, profiled.text
                profile_payload = profiled.json()
                assert profile_payload["reused"] is False
                assert profile_payload["features"]["analysis_method"] == "deterministic"
                assert "_safety" not in profile_payload["features"]
                reused_profile = await client.post(
                    "/api/workspace/style-profiles",
                    json={
                        "name": "Different display name",
                        "source_type": "user_owned",
                        "source_label": "Integration fixture",
                        "language": "zh-CN",
                        "raw_text": reference_text,
                        "rights_attested": True,
                    },
                )
                assert reused_profile.status_code == 200
                assert reused_profile.json()["id"] == profile_payload["id"]
                assert reused_profile.json()["reused"] is True
                async with AsyncSessionLocal() as verification:
                    assert await verification.scalar(
                        select(func.count()).select_from(ModelCall).where(ModelCall.user_id == user_id)
                    ) == 0
                    assert await verification.scalar(
                        select(func.count())
                        .select_from(MemoryEmbeddingTask)
                        .where(MemoryEmbeddingTask.user_id == user_id)
                    ) == 0

                provider_catalog = await client.get("/api/providers")
                assert provider_catalog.status_code == 200, provider_catalog.text
                catalog_payload = provider_catalog.json()
                assert [role["id"] for role in catalog_payload["model_roles"]] == [
                    "narrative_author",
                    "structured_extraction",
                    "continuity_revision",
                    "summary",
                    "embedding",
                ]
                embedding_role = catalog_payload["model_roles"][-1]
                assert embedding_role["configuration_source"] == "deployment"
                assert embedding_role["user_configurable"] is False
                assert set(embedding_role["deployment"]) == {
                    "provider",
                    "model",
                    "dimensions",
                    "version",
                }
                assert catalog_payload["effective_routes"]["normal_chat"] == {
                    "purpose": "normal_chat",
                    "provider": "deepinfra",
                    "model": "zai-org/GLM-5.2",
                    "source": "user_route",
                    "max_input_tokens": 10000,
                    "default_output_tokens": 2400,
                    "hard_output_tokens": 4096,
                }
                assert catalog_payload["route_history"] == []
                assert "deepinfra_base_url" not in catalog_payload

                empty_revert = await client.post("/api/providers/routes/revert")
                assert empty_revert.status_code == 409

                changed_routes = dict(catalog_payload["purpose_defaults"])
                route_update = await client.put(
                    "/api/providers/routes",
                    json={"routes": changed_routes},
                )
                assert route_update.status_code == 200, route_update.text
                update_payload = route_update.json()
                assert update_payload["effective_routes"]["normal_chat"]["model"] == (
                    "Qwen/Qwen3-Max"
                )
                assert update_payload["route_change"]["action"] == "update"
                assert update_payload["route_change"]["before_routes"]["normal_chat"] == (
                    "zai-org/GLM-5.2"
                )

                route_history = await client.get("/api/providers/routes/history")
                assert route_history.status_code == 200, route_history.text
                assert route_history.json()["route_history"][0]["id"] == (
                    update_payload["route_change"]["id"]
                )

                route_revert = await client.post("/api/providers/routes/revert")
                assert route_revert.status_code == 200, route_revert.text
                revert_payload = route_revert.json()
                assert revert_payload["effective_routes"]["normal_chat"]["model"] == (
                    "zai-org/GLM-5.2"
                )
                assert revert_payload["route_change"]["action"] == "revert"
                assert revert_payload["route_change"]["restored_change_id"] == (
                    update_payload["route_change"]["id"]
                )
                no_op_update = await client.put(
                    "/api/providers/routes",
                    json={"routes": revert_payload["purpose_routes"]},
                )
                assert no_op_update.status_code == 200, no_op_update.text
                assert no_op_update.json()["route_change"] is None
                route_history = await client.get("/api/providers/routes/history")
                assert [item["action"] for item in route_history.json()["route_history"]] == [
                    "revert",
                    "update",
                ]

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
                        "style_profile_id": profile_payload["id"],
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
                assert workspace["planned_chapter_count"] == 12
                assert workspace["target_chapter_length"] == 1800
                assert workspace["chapter_length_unit"] == "characters"
                assert workspace["roadmap_version"] == 1
                assert workspace["roadmap_source"] == "deterministic_fallback"
                assert len(workspace["chapters"]) == 12
                assert workspace["chapters"][0]["status"] == "completed"
                assert workspace["chapters"][1]["status"] == "active"
                assert all(
                    chapter["status"] == "planned" for chapter in workspace["chapters"][2:]
                )

                async with AsyncSessionLocal() as verification:
                    story_row = await verification.get(Story, UUID(story_id))
                    assert story_row is not None
                    assert story_row.style_profile_id == UUID(profile_payload["id"])
                    stored_profile = await verification.get(
                        StyleProfile, UUID(profile_payload["id"])
                    )
                    assert stored_profile is not None
                    assert "_safety" in stored_profile.features
                    assert reference_text[:80] not in str(stored_profile.features)
                    world_row = await verification.get(World, story_row.world_id)
                    assert world_row is not None
                    world_row.rules = {
                        "impossible_actions": [
                            {
                                "action": "teleport",
                                "reason": "Teleportation does not exist in the archive.",
                            }
                        ]
                    }
                    before_invalid_messages = len(
                        list(
                            (
                                await verification.scalars(
                                    select(Message).where(Message.story_id == story_row.id)
                                )
                            ).all()
                        )
                    )
                    before_invalid_generations = len(
                        list(
                            (
                                await verification.scalars(
                                    select(GenerationRequest).where(
                                        GenerationRequest.story_id == story_row.id
                                    )
                                )
                            ).all()
                        )
                    )
                    await verification.commit()

                impossible = await client.post(
                    "/api/chat/send",
                    json={
                        "message": "I teleport through the sealed archive door.",
                        "story_id": story_id,
                        "branch_id": main_branch_id,
                        "branch_version": 0,
                    },
                )
                assert impossible.status_code == 422
                assert "Teleportation does not exist" in impossible.json()["detail"]
                async with AsyncSessionLocal() as verification:
                    assert len(
                        list(
                            (
                                await verification.scalars(
                                    select(Message).where(Message.story_id == UUID(story_id))
                                )
                            ).all()
                        )
                    ) == before_invalid_messages
                    assert len(
                        list(
                            (
                                await verification.scalars(
                                    select(GenerationRequest).where(
                                        GenerationRequest.story_id == UUID(story_id)
                                    )
                                )
                            ).all()
                        )
                    ) == before_invalid_generations
                    active_chapter = await verification.scalar(
                        select(StoryChapter).where(
                            StoryChapter.story_id == UUID(story_id),
                            StoryChapter.status == "active",
                        )
                    )
                    assert active_chapter is not None
                    assert active_chapter.chapter_number == 2
                    story_row = await verification.get(Story, UUID(story_id))
                    world_row = await verification.get(World, story_row.world_id)
                    world_row.rules = {}
                    await verification.commit()

                original_generate = LLMGateway.generate

                async def copied_reference(_gateway, request):
                    return LLMResponse(
                        provider=request.provider,
                        model=request.model,
                        text=reference_text,
                        raw={"dry_run": True},
                    )

                monkeypatch.setattr(LLMGateway, "generate", copied_reference)
                overlap_key = f"journey-{marker}-overlap"
                overlap = await client.post(
                    "/api/chat/send",
                    headers={"Idempotency-Key": overlap_key},
                    json={
                        "message": "I inspect the archive without deciding what to take.",
                        "story_id": story_id,
                        "branch_id": main_branch_id,
                        "branch_version": 0,
                        "idempotency_key": overlap_key,
                    },
                )
                assert overlap.status_code == 422
                assert "overlapped the reference" in overlap.json()["detail"]
                monkeypatch.setattr(LLMGateway, "generate", original_generate)
                async with AsyncSessionLocal() as verification:
                    copied_assistant = await verification.scalar(
                        select(Message).where(
                            Message.story_id == UUID(story_id),
                            Message.role == "assistant",
                            Message.content == reference_text,
                        )
                    )
                    assert copied_assistant is None
                    blocked_generation = await verification.scalar(
                        select(GenerationRequest).where(
                            GenerationRequest.user_id == user_id,
                            GenerationRequest.idempotency_key == overlap_key,
                        )
                    )
                    assert blocked_generation is not None
                    assert blocked_generation.status == "failed"

                stale_route = await client.post(
                    "/api/chat/send",
                    headers={"Idempotency-Key": f"journey-{marker}-stale-route"},
                    json={
                        "message": "This stale client must not write a turn.",
                        "story_id": story_id,
                        "branch_id": main_branch_id,
                        "branch_version": 0,
                        "provider": "deepinfra",
                        "model": "Qwen/Qwen3-Max",
                        "idempotency_key": f"journey-{marker}-stale-route",
                    },
                )
                assert stale_route.status_code == 409
                unchanged_workspace = await client.get(
                    "/api/workspace",
                    params={"story_id": story_id, "branch_id": main_branch_id},
                )
                assert unchanged_workspace.status_code == 200
                assert len(unchanged_workspace.json()["messages"]) == len(workspace["messages"]) + 1

                preview = await client.post(
                    "/api/chat/context-preview",
                    json={
                        "message": "I inspect the key.",
                        "story_id": story_id,
                        "branch_id": main_branch_id,
                        "purpose": "normal_chat",
                    },
                )
                assert preview.status_code == 200, preview.text
                assert preview.json()["effective_route"]["model"] == "zai-org/GLM-5.2"
                assert preview.json()["effective_route"]["source"] == "user_route"

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
                assert first_reply["model_call"]["model"] == "zai-org/GLM-5.2"
                assert first_reply["content"].startswith(
                    f"## 2. {workspace['chapters'][1]['title']}"
                )
                after_first_turn = await client.get(
                    "/api/workspace",
                    params={"story_id": story_id, "branch_id": main_branch_id},
                )
                first_turn_chapters = after_first_turn.json()["chapters"]
                assert first_turn_chapters[1]["status"] == "completed"
                assert first_turn_chapters[1]["message_id"] == first_reply["message_id"]
                assert first_turn_chapters[2]["status"] == "active"

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
                after_regeneration = await client.get(
                    "/api/workspace",
                    params={"story_id": story_id, "branch_id": main_branch_id},
                )
                assert after_regeneration.json()["chapters"][2]["status"] == "active"

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
                after_stream = await client.get(
                    "/api/workspace",
                    params={"story_id": story_id, "branch_id": main_branch_id},
                )
                assert after_stream.json()["chapters"][2]["status"] == "completed"
                assert after_stream.json()["chapters"][3]["status"] == "active"

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
                    latest_assistant = await verification.scalar(
                        select(Message)
                        .where(
                            Message.story_id == story_id,
                            Message.branch_id == main_branch_id,
                            Message.role == "assistant",
                        )
                        .order_by(Message.created_at.desc(), Message.id.desc())
                    )
                    assert latest_assistant is not None
                    assert latest_assistant.meta.get("partial") is not True
                    assert "A stable checkpoint." not in latest_assistant.content

                branched = await client.post(
                    f"/api/workspace/stories/{story_id}/branches",
                    json={"name": "Refuse the archive"},
                )
                assert branched.status_code == 200, branched.text
                branch_workspace = branched.json()
                new_branch_id = branch_workspace["branch_id"]
                assert new_branch_id != main_branch_id
                assert len(branch_workspace["branches"]) == 2
                assert len(branch_workspace["chapters"]) == 12
                assert branch_workspace["chapters"][0]["status"] == "completed"
                assert branch_workspace["chapters"][0]["message_id"] != (
                    workspace["chapters"][0]["message_id"]
                )
                assert branch_workspace["ending_title"] == workspace["ending_title"]

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
