import asyncio

from app.schemas.llm import LLMRequest, LLMResponse
from app.services.context_assembler import ContextAssembly
from app.services.story_engine import StoryEngine, split_story_response, visible_stream_story_text


class ChoiceRepairGateway:
    def request_for_purpose(self, purpose, messages):
        return LLMRequest(
            provider="deepinfra",
            model="Qwen/Qwen3-Max",
            messages=messages,
            purpose=purpose,
        )

    def normalize_request(self, request):
        return request

    async def generate(self, request):
        return LLMResponse(
            provider="deepinfra",
            model=request.model,
            text='{"choices":["检查断续语音的时间戳","联系岸上的信号分析员","自定义"]}',
        )


def test_choice_mode_extracts_cards_and_removes_custom_duplicates() -> None:
    content, choices = split_story_response(
        '雨停了。\n[STORY_CHOICES]\n["追上列车", "返回钟楼", "自定义"]',
        "choices",
    )

    assert content == "雨停了。"
    assert choices == ["追上列车", "返回钟楼"]


def test_open_mode_never_exposes_model_choices() -> None:
    content, choices = split_story_response(
        '门已经打开。\n[STORY_CHOICES]\n["进入", "离开"]',
        "open",
    )

    assert content == "门已经打开。"
    assert choices == []


def test_choice_parser_accepts_json_object_and_chinese_marker() -> None:
    content, choices = split_story_response(
        '潮水撞上玻璃。\n【剧情选项】\n```json\n{"choices":["检查信号源","联系岸上同伴","自定义"]}\n```',
        "choices",
    )

    assert content == "潮水撞上玻璃。"
    assert choices == ["检查信号源", "联系岸上同伴"]


def test_choice_parser_accepts_bullet_fallback() -> None:
    content, choices = split_story_response(
        "门锁发出轻响。\n剧情推进选项：\nA. 退到走廊观察\nB. 询问门后的人\nC. 自定义",
        "choices",
    )

    assert content == "门锁发出轻响。"
    assert choices == ["退到走廊观察", "询问门后的人"]


def test_stream_holds_back_partial_choice_marker() -> None:
    assert visible_stream_story_text("足够长的小说正文[STORY_CHO") == "足够长的"
    assert visible_stream_story_text("正文\n[STORY_CHOICES]\n[") == "正文\n"


def test_choice_mode_repairs_missing_model_options() -> None:
    engine = object.__new__(StoryEngine)
    engine.llm_gateway = ChoiceRepairGateway()
    context = ContextAssembly(
        prompt_messages=[],
        preview={
            "sections": {
                "user_preferences": ["克制的悬疑感"],
                "story_prompt": "不替主角做重大决定",
                "state": {"location": "海底通信塔"},
            }
        },
    )

    choices = asyncio.run(
        engine._ensure_story_choices("choices", "语音在噪声中再次响起。", [], context)
    )

    assert choices == ["检查断续语音的时间戳", "联系岸上的信号分析员"]
