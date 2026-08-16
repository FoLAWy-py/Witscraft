from app.services.context_assembler import _take_items, _take_recent_messages
from app.services.token_estimator import estimate_tokens, trim_to_token_budget


def test_chinese_characters_use_conservative_token_estimate() -> None:
    assert estimate_tokens("临江城的雨夜") == 6
    assert estimate_tokens("abcdefgh") == 2


def test_trim_to_token_budget_handles_chinese_text() -> None:
    text = "临江城的雨夜里有人敲响旧书店的门"

    trimmed = trim_to_token_budget(text, 8)

    assert trimmed == text[:8]
    assert estimate_tokens(trimmed) <= 8


def test_first_long_item_cannot_break_section_budget() -> None:
    selected = _take_items(["临" * 100], 12)

    assert len(selected) == 1
    assert estimate_tokens(selected[0]) <= 12


def test_latest_long_message_cannot_break_recent_message_budget() -> None:
    selected = _take_recent_messages(
        [{"role": "assistant", "content": "雨" * 100}],
        15,
    )

    assert len(selected) == 1
    assert estimate_tokens(selected[0]["content"]) <= 15
