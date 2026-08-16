import pytest
from pydantic import ValidationError

from app.schemas.chat import CreateStoryRequest, StoryState


def test_new_story_state_is_neutral() -> None:
    state = StoryState()

    assert state.location == "未设定"
    assert state.time == "未设定"
    assert state.inventory == []
    assert state.open_threads == []


def test_custom_opening_requires_user_text() -> None:
    with pytest.raises(ValidationError):
        CreateStoryRequest(
            title="新故事",
            genre="悬疑",
            world_name="新世界",
            premise="一个完整的故事前提",
            protagonist_name="主角",
            protagonist_role="调查员",
            tone="克制",
            opening_mode="custom",
            opening_text="   ",
        )


def test_blank_opening_accepts_no_opening_text() -> None:
    request = CreateStoryRequest(
        title="新故事",
        genre="悬疑",
        world_name="新世界",
        premise="一个完整的故事前提",
        protagonist_name="主角",
        protagonist_role="调查员",
        tone="克制",
        opening_mode="blank",
    )

    assert request.opening_text == ""
