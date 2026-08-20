import asyncio
import json
from uuid import uuid4

import pytest

from app.config import Settings
from app.llm.router import LLMGateway
from app.schemas.chat import CreateStoryRequest, StoryRoadmapChapterDraft, StoryRoadmapDraft
from app.schemas.llm import LLMResponse
from app.services.story_roadmap import (
    deterministic_initial_roadmap,
    plan_initial_roadmap,
    revise_roadmap_window,
    validate_provider_roadmap,
)


def _request(chapter_count: int = 12) -> CreateStoryRequest:
    return CreateStoryRequest(
        title="潮汐档案",
        genre="悬疑",
        world_name="临海城",
        premise="退潮后的档案馆出现了一扇只在午夜开启的门。",
        protagonist_name="林岚",
        protagonist_role="负责调查失踪记录的档案员",
        tone="克制而紧张",
        planned_chapter_count=chapter_count,
    )


@pytest.mark.parametrize("chapter_count", [3, 12, 120])
def test_deterministic_roadmap_covers_the_complete_requested_range(chapter_count: int) -> None:
    roadmap = deterministic_initial_roadmap(_request(chapter_count))

    assert len(roadmap.chapters) == chapter_count
    assert [chapter.chapter_number for chapter in roadmap.chapters] == list(
        range(1, chapter_count + 1)
    )
    assert len({chapter.title for chapter in roadmap.chapters}) == chapter_count
    assert "林岚" in roadmap.ending_title
    objectives = " ".join(chapter.objective for chapter in roadmap.chapters)
    assert "替玩家决定" not in objectives
    if chapter_count > 3:
        assert "留给玩家" in objectives


def test_provider_roadmap_rejects_missing_or_duplicate_chapters() -> None:
    duplicate = StoryRoadmapDraft(
        ending_title="结局",
        chapters=[
            StoryRoadmapChapterDraft(chapter_number=1, title="一", objective="目标一"),
            StoryRoadmapChapterDraft(chapter_number=2, title="二", objective="目标二"),
            StoryRoadmapChapterDraft(chapter_number=2, title="三", objective="目标三"),
        ],
    )
    with pytest.raises(ValueError, match="every chapter number"):
        validate_provider_roadmap(duplicate, expected_chapter_count=3)

    duplicate_title = duplicate.model_copy(
        update={
            "chapters": [
                StoryRoadmapChapterDraft(chapter_number=1, title="相同", objective="目标一"),
                StoryRoadmapChapterDraft(chapter_number=2, title="相同", objective="目标二"),
                StoryRoadmapChapterDraft(chapter_number=3, title="不同", objective="目标三"),
            ]
        }
    )
    with pytest.raises(ValueError, match="titles must be unique"):
        validate_provider_roadmap(duplicate_title, expected_chapter_count=3)


def test_valid_provider_roadmap_is_authoritative(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_payload = {
        "ending_title": "潮汐尽头的档案",
        "chapters": [
            {"chapter_number": 1, "title": "退潮之门", "objective": "发现门后的第一条线索。"},
            {"chapter_number": 2, "title": "失名卷宗", "objective": "追查记录被抹去的原因。"},
            {"chapter_number": 3, "title": "最后一页", "objective": "把最终选择交给玩家。"},
        ],
    }

    async def fake_generate(self: LLMGateway, request: object) -> LLMResponse:
        return LLMResponse(
            text=json.dumps(provider_payload, ensure_ascii=False),
            provider="deepinfra",
            model="Qwen/Qwen3-Max",
            input_tokens=120,
            output_tokens=180,
        )

    monkeypatch.setattr(LLMGateway, "generate", fake_generate)
    planned = asyncio.run(
        plan_initial_roadmap(
            _request(3),
            settings=Settings(dry_run_llm=True),
            user_id=uuid4(),
            request_id="roadmap-contract-test",
            purpose_routes={"normal_chat": "Qwen/Qwen3-Max"},
        )
    )

    assert planned.source == "provider"
    assert planned.draft.ending_title == provider_payload["ending_title"]
    assert [chapter.title for chapter in planned.draft.chapters] == [
        "退潮之门",
        "失名卷宗",
        "最后一页",
    ]


def test_provider_revises_only_the_supplied_future_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "ending_title": "潮汐之后",
        "chapters": [
            {"chapter_number": 7, "title": "逆流", "objective": "承接玩家拒绝交易的后果。"},
            {"chapter_number": 8, "title": "无字契约", "objective": "把新的选择交还玩家。"},
        ],
    }

    async def fake_generate(self: LLMGateway, request: object) -> LLMResponse:
        return LLMResponse(
            text=json.dumps(payload, ensure_ascii=False),
            provider="deepinfra",
            model="Qwen/Qwen3-Max",
        )

    monkeypatch.setattr(LLMGateway, "generate", fake_generate)
    gateway = LLMGateway(Settings(dry_run_llm=True))
    revision = asyncio.run(
        revise_roadmap_window(
            gateway=gateway,
            future_chapters=[
                {"chapter_number": 7, "title": "旧七", "objective": "旧目标七"},
                {"chapter_number": 8, "title": "旧八", "objective": "旧目标八"},
            ],
            current_ending_title="旧结局",
            player_action="我拒绝交易。",
            accepted_chapter="交易被拒绝。",
            story_state={"objective": "离开港口"},
        )
    )

    assert revision is not None
    assert revision.ending_title == "潮汐之后"
    assert [chapter.chapter_number for chapter in revision.chapters] == [7, 8]
