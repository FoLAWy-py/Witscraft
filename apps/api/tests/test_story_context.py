import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.schemas.chat import ChatRequest, StoryState
from app.services.story_engine import StoryEngine


def test_context_excludes_current_turn_and_uses_latest_summary() -> None:
    engine = StoryEngine.__new__(StoryEngine)
    engine._load_state = AsyncMock(return_value=StoryState())
    engine._load_relationships = AsyncMock(return_value=[])
    engine._load_memories = AsyncMock(return_value=[])
    engine._load_canon_facts = AsyncMock(return_value=[])
    engine._load_world_context = AsyncMock(return_value={"name": "临江城"})
    engine._load_character_context = AsyncMock(return_value={"name": "林舟"})
    engine._load_user_preferences = AsyncMock(return_value=[])
    covered_message_id = uuid4()
    engine._load_latest_summary = AsyncMock(
        return_value=SimpleNamespace(
            content="林舟已经进入旧书店地下室。",
            to_message_id=covered_message_id,
        )
    )
    engine._load_recent_messages = AsyncMock(return_value=[])
    story = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        custom_prompt="",
        interaction_mode="open",
    )
    branch = SimpleNamespace(id=uuid4())
    current_user_message_id = uuid4()
    request = ChatRequest(message="检查那扇门", story_id=str(story.id))

    _, _, context = asyncio.run(
        engine._assemble_context(
            story,
            branch,
            request,
            recent_exclude_message_ids={current_user_message_id},
        )
    )

    engine._load_recent_messages.assert_awaited_once_with(
        story.id,
        branch.id,
        {current_user_message_id},
        covered_message_id,
    )
    developer_prompt = context.prompt_messages[1].content
    assert "林舟已经进入旧书店地下室" in developer_prompt
    assert developer_prompt.count("检查那扇门") == 0
    assert context.prompt_messages[-1].content == "检查那扇门"
