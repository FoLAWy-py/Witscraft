from app.routers.workspace_onboarding import (
    _choose_interview_focus,
    _extract_streamed_json_string,
    _finalize_story_interview,
    _story_interview_missing_fields,
)
from app.main import app
from app.schemas.chat import StoryInterviewDraft, StoryInterviewResponse, StoryState
from app.services.context_assembler import assemble_story_context


def test_onboarding_router_preserves_public_openapi_contract() -> None:
    schema = app.openapi()
    expected_operations = {
        "/api/workspace/style-profiles": {
            "post": "analyze_style_profile_api_workspace_style_profiles_post"
        },
        "/api/workspace/story-draft": {
            "post": "generate_story_draft_api_workspace_story_draft_post"
        },
        "/api/workspace/story-interview": {
            "post": "continue_story_interview_api_workspace_story_interview_post"
        },
        "/api/workspace/story-interview/stream": {
            "post": "stream_story_interview_api_workspace_story_interview_stream_post"
        },
        "/api/workspace/preferences": {
            "get": "get_user_preferences_api_workspace_preferences_get",
            "put": "update_user_preferences_api_workspace_preferences_put",
        },
    }

    for path, methods in expected_operations.items():
        assert {
            method: schema["paths"][path][method]["operationId"] for method in methods
        } == methods


def _complete_draft(**overrides) -> StoryInterviewDraft:
    values = {
        "title": "雨城来信",
        "genre": "都市悬疑",
        "world_name": "临江城",
        "premise": "失踪记者留下会改写内容的信。",
        "protagonist_name": "林舟",
        "protagonist_role": "追查姐姐失踪真相的旧书店店员",
        "tone": "克制、潮湿、慢热",
        "opening_mode": "blank",
        "opening_text": "",
        "custom_prompt": "第三人称限知，不提前揭示信件来源。",
    }
    values.update(overrides)
    return StoryInterviewDraft(**values)


def test_interview_requires_explicit_complete_card() -> None:
    draft = _complete_draft(title="", protagonist_role="")

    assert _story_interview_missing_fields(draft) == ["title", "protagonist_role"]


def test_custom_opening_is_required_only_when_selected() -> None:
    assert _story_interview_missing_fields(_complete_draft()) == []
    assert _story_interview_missing_fields(_complete_draft(opening_mode="custom")) == [
        "opening_text"
    ]


def test_interview_requires_generated_custom_prompt() -> None:
    assert _story_interview_missing_fields(_complete_draft(custom_prompt="")) == ["custom_prompt"]


def test_complete_interview_uses_explicit_ready_message() -> None:
    result = _finalize_story_interview(
        StoryInterviewResponse(
            assistant_message="都整理好了。",
            options=["继续提问"],
            draft=_complete_draft(),
        )
    )

    assert result.ready_for_confirmation is True
    assert result.options == []
    assert "小说已就绪" in result.assistant_message
    assert "确认并创建小说" in result.assistant_message


def test_incomplete_interview_keeps_one_question_and_options() -> None:
    result = _finalize_story_interview(
        StoryInterviewResponse(
            assistant_message="你喜欢现实城市吗？还是架空世界？",
            options=[],
            draft=_complete_draft(world_name=""),
        )
    )

    assert result.assistant_message == "你喜欢现实城市吗？"
    assert len(result.options) >= 2
    assert result.missing_fields == ["world_name"]


def test_incomplete_interview_adds_a_question_after_a_status_update() -> None:
    result = _finalize_story_interview(
        StoryInterviewResponse(
            assistant_message="已根据设定生成小说专属 Prompt。",
            draft=_complete_draft(title=""),
        )
    )

    assert result.assistant_message.count("？") == 1
    assert result.assistant_message.endswith("你更喜欢哪一种？")


def test_interview_focus_changes_with_accumulated_story_information() -> None:
    initial = StoryInterviewDraft()
    developed = StoryInterviewDraft(
        genre="近未来悬疑",
        world_name="被潮汐淹没一半的上海",
        premise="潜水员收到来自失踪姐姐的实时语音。",
        protagonist_role="负责维护海底通信塔的潜水员",
    )

    assert _choose_interview_focus(initial, "我有一个故事灵感") == "premise"
    assert _choose_interview_focus(developed, "主角叫沈澜") == "protagonist_name"


def test_model_selected_dynamic_focus_overrides_static_missing_order() -> None:
    result = _finalize_story_interview(
        StoryInterviewResponse(
            assistant_message="既然上海被潮汐淹没了一半，沈澜维护通信塔时最想查清什么？",
            options=["姐姐失踪的真相", "语音信号的来源"],
            question_focus="protagonist_role",
            draft=StoryInterviewDraft(
                genre="近未来悬疑",
                world_name="潮汐上海",
                premise="失踪者通过海底通信塔发来实时语音。",
                protagonist_name="沈澜",
            ),
        ),
        latest_user_message="主角叫沈澜，是通信塔维护员",
    )

    assert result.question_focus == "protagonist_role"
    assert result.missing_fields[0] == "title"
    assert result.options == ["姐姐失踪的真相", "语音信号的来源"]


def test_fallback_question_reuses_collected_story_context() -> None:
    result = _finalize_story_interview(
        StoryInterviewResponse(
            assistant_message="我记下了这些设定。",
            draft=StoryInterviewDraft(
                genre="近未来悬疑",
                world_name="潮汐上海",
                premise="",
            ),
        )
    )

    assert result.question_focus == "premise"
    assert "近未来悬疑" in result.assistant_message
    assert "潮汐上海" in result.assistant_message


def test_streaming_json_decoder_exposes_only_complete_text() -> None:
    assert (
        _extract_streamed_json_string(
            '{"assistant_message":"你好\\n世界","options":', "assistant_message"
        )
        == "你好\n世界"
    )
    assert (
        _extract_streamed_json_string('{"assistant_message":"\\u4f60\\u597', "assistant_message")
        == "你"
    )


def test_open_interview_mode_removes_all_generated_options() -> None:
    result = _finalize_story_interview(
        StoryInterviewResponse(
            assistant_message="先确定故事发生在哪里？",
            options=["现实城市", "架空世界", "自定义"],
            draft=_complete_draft(world_name="", interaction_mode="open"),
        )
    )

    assert result.options == []


def test_choice_interview_mode_filters_model_custom_option() -> None:
    result = _finalize_story_interview(
        StoryInterviewResponse(
            assistant_message="先确定故事发生在哪里？",
            options=["现实城市", "架空世界", "自定义"],
            draft=_complete_draft(world_name="", interaction_mode="choices"),
        )
    )

    assert result.options == ["现实城市", "架空世界"]


def test_preferences_and_story_prompt_enter_generation_context() -> None:
    context = assemble_story_context(
        "继续",
        StoryState(),
        [],
        [],
        {"name": "临江城"},
        {"name": "林舟"},
        ["偏爱慢热悬疑", "避免无意义反转"],
        "第三人称限知，不提前揭示真相。",
        "choices",
        [],
    )

    developer_prompt = context.prompt_messages[1].content
    assert "偏爱慢热悬疑" in developer_prompt
    assert "避免无意义反转" in developer_prompt
    assert "第三人称限知，不提前揭示真相。" in developer_prompt
    assert context.preview["sections"]["story_prompt"] == "第三人称限知，不提前揭示真相。"


def test_story_summary_enters_generation_context() -> None:
    context = assemble_story_context(
        "继续",
        StoryState(),
        [],
        [],
        {"name": "临江城"},
        {"name": "林舟"},
        [],
        "",
        "open",
        [],
        "林舟已确认旧书店地下室存在一扇无法从内部开启的门。",
    )

    developer_prompt = context.prompt_messages[1].content
    assert "[Story Summary]" in developer_prompt
    assert "旧书店地下室" in developer_prompt
    assert "旧书店地下室" in context.preview["sections"]["story_summary"]
