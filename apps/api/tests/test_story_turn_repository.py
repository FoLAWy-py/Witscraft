import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.services.story_turn_repository import StoryTurnRepository


def test_message_lifecycle_stages_changes_without_committing() -> None:
    async def scenario() -> None:
        session = Mock()
        session.flush = AsyncMock()
        session.execute = AsyncMock()
        repository = StoryTurnRepository(session)
        story_id = uuid4()
        branch_id = uuid4()
        chapter_id = uuid4()

        user_message = await repository.create_user_message(
            story_id,
            branch_id,
            "走进雨中",
            chapter_id,
        )
        assert user_message.role == "user"
        assert user_message.content == "走进雨中"
        assert user_message.chapter_id == chapter_id
        assert user_message.meta == {"author": "你"}

        partial = await repository.upsert_partial_assistant_message(
            story_id,
            branch_id,
            "雨势渐急",
            chapter_id=chapter_id,
        )
        assert partial.role == "assistant"
        assert partial.content == "雨势渐急"
        assert partial.meta == {"author": "叙事引擎", "partial": True, "stream": True}

        replacement_chapter_id = uuid4()
        updated = await repository.upsert_partial_assistant_message(
            story_id,
            branch_id,
            "雨幕遮住山路",
            partial,
            replacement_chapter_id,
        )
        assert updated is partial
        assert updated.content == "雨幕遮住山路"
        assert updated.chapter_id == replacement_chapter_id
        assert session.add.call_count == 2
        assert session.flush.await_count == 2
        assert not hasattr(session, "commit") or session.commit.call_count == 0

        await repository.delete_message_derivatives(uuid4())
        assert session.execute.await_count == 3

    asyncio.run(scenario())
