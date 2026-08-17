from app.schemas.chat import StoryState
from app.services.context_assembler import (
    CONTEXT_INPUT_TOKEN_TARGET,
    assemble_story_context,
    _take_items,
    _take_recent_messages,
)
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


def test_dynamic_budget_reallocates_unused_sections_to_recent_messages() -> None:
    context = assemble_story_context(
        "继续",
        StoryState(),
        [],
        [],
        {},
        {},
        [],
        "",
        "open",
        [
            {"role": "assistant", "content": "雨" * 240}
            for _ in range(12)
        ],
    )

    assert context.preview["budgets"]["recent_messages"] > 900
    selection = context.preview["section_selection"]["recent_messages"]
    assert selection["selected_tokens"] <= selection["allocated_tokens"]
    assert selection["source"] == "uncovered branch message timeline"
    assert context.preview["budget_policy"]["allocated"] <= context.preview["budget_policy"][
        "section_pool"
    ]


def test_long_user_input_reduces_section_pool_but_keeps_prompt_under_target() -> None:
    context = assemble_story_context(
        "雨" * 4000,
        StoryState(
            location="临江城" * 80,
            objective="找到钥匙" * 100,
            inventory=["旧钥匙" * 30 for _ in range(20)],
            open_threads=["钟楼谜题" * 30 for _ in range(20)],
        ),
        ["记忆" * 300 for _ in range(10)],
        ["事实" * 300 for _ in range(10)],
        {"description": "世界" * 1000},
        {"identity": "角色" * 1000},
        ["偏好" * 200],
        "规则" * 1000,
        "open",
        [{"role": "assistant", "content": "对话" * 500}],
        "摘要" * 1000,
    )

    assert context.preview["budget_policy"]["section_pool"] < 5460
    assert context.preview["estimated_tokens"]["prompt_total"] <= CONTEXT_INPUT_TOKEN_TARGET
    assert sum(context.preview["budgets"].values()) <= context.preview["budget_policy"][
        "section_pool"
    ]
    assert all(
        section["selected_tokens"] <= section["allocated_tokens"]
        for section in context.preview["section_selection"].values()
    )


def test_story_state_is_actually_trimmed_and_preview_explains_why() -> None:
    marker = "SHOULD_BE_TRIMMED"
    state = StoryState(
        location="码头" * 300 + marker,
        time="午夜",
        mood="紧张",
        objective="阻止钟楼倒计时" * 200 + marker,
        inventory=[f"物品-{index}-" + "重" * 80 for index in range(30)],
        open_threads=[f"线索-{index}-" + "谜" * 80 for index in range(30)],
    )

    context = assemble_story_context(
        "继续",
        state,
        [],
        [],
        {},
        {},
        [],
        "",
        "open",
        [],
    )

    selection = context.preview["section_selection"]["state"]
    assert selection["truncated"] is True
    assert selection["truncation_reason"] == "dynamic_section_budget"
    assert selection["selected_tokens"] <= selection["allocated_tokens"]
    assert marker not in str(context.preview["sections"]["state"])
    assert context.preview["token_estimator"] == {
        "name": "conservative-multilingual-v1",
        "calibrated_to_provider_tokenizer": False,
    }


def test_world_hard_rules_are_selected_before_long_descriptive_lore() -> None:
    context = assemble_story_context(
        "继续",
        StoryState(),
        [],
        [],
        {
            "name": "潮汐城",
            "description": "背景传说" * 1000,
            "genre": "悬疑",
            "rules": "时间旅行绝对禁止",
        },
        {},
        [],
        "",
        "open",
        [],
    )

    selected_world = context.preview["sections"]["world"]
    assert selected_world["name"] == "潮汐城"
    assert selected_world["genre"] == "悬疑"
    assert selected_world["rules"] == "时间旅行绝对禁止"
