import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from starlette.requests import Request

from app.config import Settings
from app.db.models import CanonFact, Character, MemoryItem, Story, StoryBranch, User, World
from app.db.session import AsyncSessionLocal, engine as db_engine
from app.routers.workspace import (
    export_story,
    update_branch,
    update_canon_fact,
    update_character,
    update_memory,
    update_story,
    update_world,
    workspace,
)
from app.schemas.chat import (
    UpdateBranchRequest,
    UpdateCanonFactRequest,
    UpdateCharacterRequest,
    UpdateMemoryRequest,
    UpdateStoryRequest,
    UpdateWorldRequest,
)
from app.embedding_config import EMBEDDING_VECTOR_DIMENSIONS, LOCAL_EMBEDDING_MODEL
from app.services.embeddings import embedding_content_hash, stored_embedding
from app.services.story_engine import StoryEngine


async def _expect_not_found(awaitable) -> None:
    with pytest.raises(HTTPException) as caught:
        await awaitable
    assert caught.value.status_code == 404


def test_cross_user_workspace_resource_matrix_is_denied() -> None:
    async def scenario() -> None:
        marker = uuid4().hex
        user_ids = []
        try:
            async with AsyncSessionLocal() as session:
                users = [
                    User(
                        email=f"authorization-{marker}-{index}@example.invalid",
                        display_name=f"user-{index}",
                        email_verified_at=datetime.now(timezone.utc),
                    )
                    for index in range(2)
                ]
                session.add_all(users)
                await session.flush()
                user_ids = [user.id for user in users]

                worlds = [
                    World(user_id=user.id, name=f"world-{index}", rules={}, lorebook=[], tone={})
                    for index, user in enumerate(users)
                ]
                session.add_all(worlds)
                await session.flush()
                stories = [
                    Story(user_id=user.id, world_id=world.id, title=f"story-{index}")
                    for index, (user, world) in enumerate(zip(users, worlds, strict=True))
                ]
                session.add_all(stories)
                await session.flush()
                branches = [
                    StoryBranch(story_id=story.id, name="main") for story in stories
                ]
                session.add_all(branches)
                await session.flush()
                for story, branch in zip(stories, branches, strict=True):
                    story.current_branch_id = branch.id

                characters = [
                    Character(
                        user_id=user.id,
                        world_id=world.id,
                        name=f"character-{index}",
                        persona={},
                        speaking_style={},
                        relationship_to_user={},
                        constraints={},
                    )
                    for index, (user, world) in enumerate(zip(users, worlds, strict=True))
                ]
                session.add_all(characters)
                memories = [
                    MemoryItem(
                        user_id=user.id,
                        story_id=story.id,
                        branch_id=branch.id,
                        memory_type="test",
                        content=f"private-memory-{index}",
                        entity_tags=[],
                        meta={},
                    )
                    for index, (user, story, branch) in enumerate(
                        zip(users, stories, branches, strict=True)
                    )
                ]
                session.add_all(memories)
                facts = [
                    CanonFact(
                        story_id=story.id,
                        branch_id=branch.id,
                        fact_type="test",
                        content=f"private-fact-{index}",
                    )
                    for index, (story, branch) in enumerate(zip(stories, branches, strict=True))
                ]
                session.add_all(facts)
                await session.commit()

                attacker_id = users[0].id
                victim_story = stories[1]
                victim_branch = branches[1]
                victim_world = worlds[1]
                victim_character = characters[1]
                victim_memory = memories[1]
                victim_fact = facts[1]
                http_request = Request(
                    {
                        "type": "http",
                        "method": "PATCH",
                        "path": "/",
                        "headers": [],
                        "query_string": b"",
                        "client": ("127.0.0.1", 1),
                        "server": ("testserver", 80),
                    }
                )

                await _expect_not_found(
                    update_story(
                        str(victim_story.id),
                        UpdateStoryRequest(title="stolen"),
                        session,
                        attacker_id,
                    )
                )
                await _expect_not_found(
                    update_branch(
                        str(stories[0].id),
                        str(victim_branch.id),
                        UpdateBranchRequest(name="stolen"),
                        session,
                        attacker_id,
                    )
                )
                await _expect_not_found(
                    update_world(
                        str(victim_world.id),
                        UpdateWorldRequest(name="stolen", description="", genre=""),
                        None,
                        session,
                        attacker_id,
                    )
                )
                await _expect_not_found(
                    update_character(
                        str(victim_character.id),
                        UpdateCharacterRequest(name="stolen", role=""),
                        None,
                        session,
                        attacker_id,
                    )
                )
                await _expect_not_found(
                    update_memory(
                        str(victim_memory.id),
                        UpdateMemoryRequest(content="stolen", importance=5),
                        http_request,
                        None,
                        session,
                        Settings(dry_run_llm=True),
                        attacker_id,
                    )
                )
                await _expect_not_found(
                    update_canon_fact(
                        str(victim_fact.id),
                        UpdateCanonFactRequest(content="stolen", importance=5),
                        None,
                        session,
                        attacker_id,
                    )
                )
                await _expect_not_found(
                    export_story(
                        str(victim_story.id),
                        str(victim_branch.id),
                        "json",
                        session,
                        attacker_id,
                    )
                )

                response = await workspace(
                    story_id=str(victim_story.id),
                    branch_id=str(victim_branch.id),
                    session=session,
                    user_id=attacker_id,
                )
                assert response.story_id == str(stories[0].id)
                assert "private-memory-1" not in response.retrieved_memories
                assert "private-fact-1" not in response.canon_facts

                engine = object.__new__(StoryEngine)
                engine.session = session
                engine.user_id = attacker_id
                await _expect_not_found(engine._get_story(victim_story.id))

                await session.refresh(victim_story)
                await session.refresh(victim_world)
                await session.refresh(victim_character)
                await session.refresh(victim_memory)
                await session.refresh(victim_fact)
                assert victim_story.title == "story-1"
                assert victim_world.name == "world-1"
                assert victim_character.name == "character-1"
                assert victim_memory.content == "private-memory-1"
                assert victim_fact.content == "private-fact-1"
        finally:
            if user_ids:
                async with AsyncSessionLocal() as cleanup:
                    await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
                    await cleanup.commit()
            await db_engine.dispose()

    asyncio.run(scenario())


def test_memory_edit_reuses_or_refreshes_embedding_and_rejects_duplicates() -> None:
    async def scenario() -> None:
        marker = uuid4().hex
        user_id = None
        try:
            async with AsyncSessionLocal() as session:
                user = User(
                    email=f"memory-edit-{marker}@example.invalid",
                    display_name="memory-editor",
                    email_verified_at=datetime.now(timezone.utc),
                )
                session.add(user)
                await session.flush()
                user_id = user.id
                world = World(user_id=user.id, name="memory-world", rules={}, lorebook=[], tone={})
                session.add(world)
                await session.flush()
                story = Story(user_id=user.id, world_id=world.id, title="memory-story")
                session.add(story)
                await session.flush()
                branch = StoryBranch(story_id=story.id, name="main")
                session.add(branch)
                await session.flush()
                story.current_branch_id = branch.id

                original_embedded_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
                editable = MemoryItem(
                    user_id=user.id,
                    story_id=story.id,
                    branch_id=branch.id,
                    memory_type="test",
                    content="Mira keeps the brass key",
                    importance=5,
                    entity_tags=["Mira", "brass key"],
                    meta={},
                    embedding=[0.25],
                    embedding_model="local:deterministic-blake2b-128",
                    embedding_dimensions=1,
                    embedding_version="v1",
                    content_hash=embedding_content_hash("Mira keeps the brass key"),
                    embedded_at=original_embedded_at,
                )
                duplicate = MemoryItem(
                    user_id=user.id,
                    story_id=story.id,
                    branch_id=branch.id,
                    memory_type="test",
                    content="The archive door is sealed",
                    importance=6,
                    entity_tags=["archive"],
                    meta={},
                    content_hash=embedding_content_hash("The archive door is sealed"),
                )
                session.add_all([editable, duplicate])
                await session.commit()

                http_request = Request(
                    {
                        "type": "http",
                        "method": "PATCH",
                        "path": "/",
                        "headers": [],
                        "state": {"request_id": f"memory-edit-{marker}"},
                    }
                )
                settings = Settings(dry_run_llm=True)

                await update_memory(
                    str(editable.id),
                    UpdateMemoryRequest(content="Mira keeps the brass key", importance=8),
                    http_request,
                    str(story.id),
                    session,
                    settings,
                    user.id,
                )
                await session.refresh(editable)
                assert editable.importance == 8
                assert editable.embedding == [0.25]
                assert editable.embedded_at == original_embedded_at

                changed_content = "Lena carries the silver compass"
                await update_memory(
                    str(editable.id),
                    UpdateMemoryRequest(content=changed_content, importance=7),
                    http_request,
                    str(story.id),
                    session,
                    settings,
                    user.id,
                )
                await session.refresh(editable)
                assert editable.content == changed_content
                assert editable.entity_tags == []
                assert editable.embedding is None
                assert len(stored_embedding(editable) or []) == EMBEDDING_VECTOR_DIMENSIONS
                assert editable.embedding_model == f"local:{LOCAL_EMBEDDING_MODEL}"
                assert editable.embedding_dimensions == EMBEDDING_VECTOR_DIMENSIONS
                assert editable.embedding_version == settings.embedding_version
                assert editable.content_hash == embedding_content_hash(changed_content)
                assert editable.embedded_at > original_embedded_at

                with pytest.raises(HTTPException) as caught:
                    await update_memory(
                        str(editable.id),
                        UpdateMemoryRequest(content="  The archive door is sealed  ", importance=9),
                        http_request,
                        str(story.id),
                        session,
                        settings,
                        user.id,
                    )
                assert caught.value.status_code == 409
                await session.refresh(editable)
                assert editable.content == changed_content
        finally:
            if user_id is not None:
                async with AsyncSessionLocal() as cleanup:
                    await cleanup.execute(delete(User).where(User.id == user_id))
                    await cleanup.commit()
            await db_engine.dispose()

    asyncio.run(scenario())
