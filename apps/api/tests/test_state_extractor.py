import asyncio

from app.schemas.chat import StoryState
from app.schemas.llm import LLMRequest, LLMResponse
from app.services.state_extractor import extract_story_updates_with_llm


class FakeGateway:
    def __init__(self, text: str):
        self.text = text

    def request_for_purpose(self, purpose, messages):
        return LLMRequest(
            provider="deepinfra",
            model="Qwen/Qwen3.5-397B-A17B",
            messages=messages,
            purpose=purpose,
            max_output_tokens=1800,
            temperature=0.2,
            top_p=0.85,
        )

    def normalize_request(self, request):
        return request

    async def generate(self, request):
        return LLMResponse(
            provider="deepinfra",
            model=request.model,
            text=self.text,
        )


def test_structured_state_update_populates_inspector_fields():
    gateway = FakeGateway(
        """{
          "location": "旧车站二号站台",
          "time": "凌晨 00:47",
          "mood": "潮湿、戒备、逐渐逼近",
          "objective": "查明旧车票上的时间指向哪一班列车",
          "inventory": ["旧车票", "录音笔", "夹层纸片"],
          "open_threads": ["07:47 的含义", "失踪兄长与车站的关系"],
          "relationships": [{"from": "周砚", "to": "周墨", "bond": "牵挂", "value": 72}],
          "memories": ["周砚在废弃的旧车站二号站台拾到旧车票。"],
          "canon_facts": ["车票背面写着 07:47。"],
          "chapter_phase": "resolution",
          "chapter_objective_resolved": true,
          "natural_break": true,
          "chapter_decision": "complete",
          "chapter_decision_reason": "车票线索已确认，场景在新问题出现前自然闭合。",
          "exceptional_break": "none"
        }"""
    )

    result = asyncio.run(
        extract_story_updates_with_llm(
            gateway,
            StoryState(objective="调查雨夜车站"),
            "周砚在废弃的旧车站二号站台拾到旧车票，带着录音笔但没有拿走夹层纸片，查明失踪兄长与车站的关系。",
            "凌晨 00:47，周墨的留言令周砚感到潮湿、戒备、危险逐渐逼近；车票背面写着 07:47。",
            chapter_context={"chapter_number": 1, "minimum_length": 1200},
        )
    )

    assert result.state.location == "旧车站二号站台"
    assert result.state.time == "凌晨 00:47"
    assert result.state.mood == "潮湿、戒备、逐渐逼近"
    assert result.state.inventory == ["旧车票", "录音笔"]
    assert result.state.open_threads == ["07:47 的含义", "失踪兄长与车站的关系"]
    assert result.relationships == [
        {"from": "周砚", "to": "周墨", "bond": "牵挂", "value": 72}
    ]
    assert result.memories == ["周砚在废弃的旧车站二号站台拾到旧车票"]
    assert result.canon_facts == ["车票背面写着 07:47"]
    assert result.source == "llm"
    assert result.chapter_progress.decision == "complete"
    assert result.chapter_progress.objective_resolved is True
    assert result.chapter_progress.natural_break is True


def test_invalid_structured_update_uses_generic_fallback_without_demo_objective():
    result = asyncio.run(
        extract_story_updates_with_llm(
            FakeGateway("not json"),
            StoryState(objective="寻找失踪的兄长", mood="克制"),
            "封锁倒计时开始。",
            "周砚留在原地观察。",
        )
    )

    assert "七号档案" not in result.state.objective
    assert result.state.objective == "寻找失踪的兄长"
    assert result.canon_facts == []
    assert result.chapter_progress.decision == "continue"


def test_explicit_kinship_populates_relationship_when_model_omits_it():
    result = asyncio.run(
        extract_story_updates_with_llm(
            FakeGateway(
                """{
                  "location": null,
                  "time": null,
                  "mood": null,
                  "objective": null,
                  "inventory": null,
                  "open_threads": null,
                  "relationships": null,
                  "memories": [],
                  "canon_facts": []
                }"""
            ),
            StoryState(),
            "周砚确认失踪兄长周墨留下了警告。",
            "录音中的声音属于周墨。",
            perspective_character="周砚",
        )
    )

    assert result.relationships == [
        {"from": "周砚", "to": "周墨", "bond": "兄长", "value": 70}
    ]


def test_relationship_title_alias_merges_with_existing_entity():
    result = asyncio.run(
        extract_story_updates_with_llm(
            FakeGateway(
                """{
                  "location": null,
                  "time": null,
                  "mood": null,
                  "objective": null,
                  "inventory": null,
                  "open_threads": null,
                  "relationships": [
                    {"from": "罗小罗", "to": "橘猫", "bond": "初步信任", "value": 40},
                    {"from": "罗小罗", "to": "烛尾", "bond": "使命引导者", "value": 55}
                  ],
                  "memories": [],
                  "canon_facts": []
                }"""
            ),
            StoryState(),
            "你到底是谁？",
            "橘猫望着罗小罗说：‘我叫烛尾’。‘烛尾’不是名字，是职阶。",
            relationships=[
                {"from": "罗小罗", "to": "橘猫", "bond": "初步信任", "value": 40}
            ],
            perspective_character="罗小罗",
        )
    )

    assert result.relationships == [
        {"from": "罗小罗", "to": "橘猫", "bond": "使命引导者", "value": 55}
    ]


def test_planned_destination_does_not_replace_current_location():
    result = asyncio.run(
        extract_story_updates_with_llm(
            FakeGateway(
                '{"location":"废弃地铁站","time":null,"mood":null,"objective":null,'
                '"inventory":null,"open_threads":null,"relationships":null,'
                '"memories":[],"canon_facts":[]}'
            ),
            StoryState(location="修车铺"),
            "我们要不要去废弃地铁站？",
            "烛尾说先准备工具，稍后再前往废弃地铁站。",
        )
    )

    assert result.state.location == "修车铺"


def test_explicit_arrival_replaces_current_location():
    result = asyncio.run(
        extract_story_updates_with_llm(
            FakeGateway(
                '{"location":"废弃地铁站","time":null,"mood":null,"objective":null,'
                '"inventory":null,"open_threads":null,"relationships":null,'
                '"memories":[],"canon_facts":[]}'
            ),
            StoryState(location="修车铺"),
            "跟着烛尾出发。",
            "十分钟后，你们抵达废弃地铁站，站在封闭的入口前。",
        )
    )

    assert result.state.location == "废弃地铁站"


def test_abstract_standing_perspective_never_becomes_location():
    result = asyncio.run(
        extract_story_updates_with_llm(
            FakeGateway(
                '{"location":"沈澜的角度","time":null,"mood":null,"objective":null,'
                '"inventory":null,"open_threads":null,"relationships":null,'
                '"memories":[],"canon_facts":[]}'
            ),
            StoryState(location="海底通信塔"),
            "站在沈澜的角度，她应该相信这段语音吗？",
            "她没有立刻回答。",
        )
    )

    assert result.state.location == "海底通信塔"


def test_valid_structured_nulls_preserve_previous_state_instead_of_regex_fallback():
    result = asyncio.run(
        extract_story_updates_with_llm(
            FakeGateway(
                '{"location":null,"time":null,"mood":null,"objective":null,'
                '"inventory":null,"open_threads":null,"relationships":null,'
                '"memories":[],"canon_facts":[]}'
            ),
            StoryState(
                location="录音室",
                objective="确认录音来源",
                inventory=["录音带"],
                open_threads=[],
            ),
            "周砚确认失踪兄长周墨留下了警告。",
            "录音中的声音属于周墨。",
        )
    )

    assert result.state.objective == "确认录音来源"
    assert result.state.inventory == ["录音带"]
    assert result.state.open_threads == []


def test_complete_inventory_can_preserve_old_item_and_remove_discarded_item():
    result = asyncio.run(
        extract_story_updates_with_llm(
            FakeGateway(
                '{"location":null,"time":null,"mood":null,"objective":null,'
                '"inventory":["纸条","铜币"],"open_threads":null,'
                '"relationships":null,"memories":[],"canon_facts":[]}'
            ),
            StoryState(inventory=["旧钥匙", "纸条"]),
            "把会暴露行踪的东西处理掉。",
            "宁舟把旧钥匙丢进河里，保留纸条，又拿起桥栏上的铜币。",
        )
    )

    assert result.state.inventory == ["纸条", "铜币"]


def test_live_shaped_overreach_is_rejected_by_deterministic_postprocessing():
    result = asyncio.run(
        extract_story_updates_with_llm(
            FakeGateway(
                """{
                  "location": null,
                  "time": null,
                  "mood": "疑惑",
                  "objective": "准备工具",
                  "inventory": null,
                  "open_threads": ["前往废弃地铁站"],
                  "relationships": null,
                  "memories": ["烛尾提议稍后再前往废弃地铁站，当前需先准备工具"],
                  "canon_facts": ["‘烛尾’是职阶，不是名字"]
                }"""
            ),
            StoryState(
                location="修车铺",
                mood="平静",
                objective="修好发动机",
                open_threads=["橘猫身份"],
            ),
            "我们要不要去废弃地铁站？",
            "橘猫说先准备工具，稍后再前往废弃地铁站。‘烛尾’不是名字，是职阶。",
        )
    )

    assert result.state.mood == "平静"
    assert result.state.objective == "修好发动机"
    assert result.state.open_threads == ["橘猫身份"]
    assert result.memories == []
    assert result.canon_facts == []
