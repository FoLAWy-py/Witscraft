import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest


def _request(**overrides) -> ChatRequest:
    values = {
        "message": "继续场景",
        "story_id": "00000000-0000-0000-0000-000000000001",
        "branch_id": "00000000-0000-0000-0000-000000000002",
    }
    values.update(overrides)
    return ChatRequest(**values)


def test_standard_chat_rejects_blank_message() -> None:
    with pytest.raises(ValidationError, match="message cannot be blank"):
        _request(message="   ")


def test_regenerate_requires_a_target_message() -> None:
    with pytest.raises(ValidationError, match="target_message_id is required"):
        _request(message="", command="regenerate")


def test_message_commands_are_non_streaming() -> None:
    with pytest.raises(ValidationError, match="non-streaming endpoint"):
        _request(
            message="",
            command="regenerate",
            target_message_id="00000000-0000-0000-0000-000000000003",
            stream=True,
        )


def test_rewrite_can_use_the_default_instruction() -> None:
    request = _request(
        message="",
        command="rewrite",
        target_message_id="00000000-0000-0000-0000-000000000003",
    )

    assert request.command == "rewrite"
    assert request.message == ""
