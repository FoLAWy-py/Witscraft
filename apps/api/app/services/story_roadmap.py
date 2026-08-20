from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.config import Settings
from app.llm.audit import CallAuditor
from app.llm.router import LLMGateway
from app.schemas.chat import CreateStoryRequest, StoryRoadmapChapterDraft, StoryRoadmapDraft
from app.schemas.llm import ChatMessage, StoryPurpose
from app.services.quota_service import QuotaExceededError


RoadmapSource = Literal["provider", "deterministic_fallback"]


@dataclass(frozen=True)
class PlannedRoadmap:
    draft: StoryRoadmapDraft
    source: RoadmapSource


def deterministic_initial_roadmap(request: CreateStoryRequest) -> StoryRoadmapDraft:
    chapter_count = request.planned_chapter_count
    premise = " ".join(request.premise.split())
    premise_excerpt = premise[:72].rstrip("，。,. ")
    protagonist = request.protagonist_name.strip()
    chapters: list[StoryRoadmapChapterDraft] = []
    for chapter_number in range(1, chapter_count + 1):
        progress = (chapter_number - 1) / max(chapter_count - 1, 1)
        if chapter_number == 1:
            stage = "异变初现"
            objective = f"让{protagonist}进入“{premise_excerpt}”的核心处境，并留下第一个可行动的问题。"
        elif chapter_number == chapter_count:
            stage = "终局回响"
            objective = (
                f"根据玩家已经作出的选择收束“{premise_excerpt}”，形成该分支独有的结局。"
            )
        elif progress < 0.3:
            stage = "暗流渐起"
            objective = f"扩大既有冲突，揭示一条与{protagonist}当前目标直接相关的新线索。"
        elif progress < 0.55:
            stage = "局势转折"
            objective = "让既有选择产生可见代价，并把一个未决线索转化为新的行动压力。"
        elif progress < 0.8:
            stage = "真相逼近"
            objective = "推进关键关系与世界规则的碰撞，但把不可逆决定留给玩家。"
        else:
            stage = "终局前夜"
            objective = "回收核心伏笔、明确剩余风险，并把分支推向最终选择。"
        chapters.append(
            StoryRoadmapChapterDraft(
                chapter_number=chapter_number,
                title=f"{stage}·{chapter_number:02d}",
                objective=objective,
            )
        )
    return StoryRoadmapDraft(
        ending_title=f"{request.title.strip()}：{protagonist}的答案",
        chapters=chapters,
    )


def validate_provider_roadmap(
    draft: StoryRoadmapDraft,
    *,
    expected_chapter_count: int,
) -> StoryRoadmapDraft:
    expected_numbers = list(range(1, expected_chapter_count + 1))
    actual_numbers = [chapter.chapter_number for chapter in draft.chapters]
    if actual_numbers != expected_numbers:
        raise ValueError("Roadmap must contain every chapter number exactly once in order")
    normalized_titles = [chapter.title.strip().casefold() for chapter in draft.chapters]
    if len(set(normalized_titles)) != len(normalized_titles):
        raise ValueError("Roadmap chapter titles must be unique")
    return draft


async def plan_initial_roadmap(
    request: CreateStoryRequest,
    *,
    settings: Settings,
    user_id: UUID,
    request_id: str | None,
    purpose_routes: Mapping[StoryPurpose, str],
) -> PlannedRoadmap:
    fallback = deterministic_initial_roadmap(request)
    auditor = CallAuditor(settings, user_id=user_id, request_id=request_id)
    gateway = LLMGateway(settings, auditor=auditor, purpose_routes=purpose_routes)
    story_brief = {
        "title": request.title.strip(),
        "genre": request.genre.strip(),
        "premise": request.premise.strip(),
        "protagonist_name": request.protagonist_name.strip(),
        "protagonist_role": request.protagonist_role.strip(),
        "tone": request.tone.strip(),
        "prose_language": request.prose_language.strip(),
        "chapter_count": request.planned_chapter_count,
    }
    messages = [
        ChatMessage(
            role="system",
            content=(
                "You plan a player-led interactive novel. Return JSON only with ending_title and "
                "chapters. chapters must contain exactly the requested count in numeric order. "
                "Every item must contain chapter_number, title, and objective. Titles must be "
                "distinct and concise. Objectives are provisional dramatic pressures, not fixed "
                "outcomes: never decide the protagonist's irreversible choices, speech, private "
                "thoughts, allegiance, sacrifice, or ending. The final chapter may frame an ending "
                "decision but must not predetermine it. Match the requested prose language."
            ),
        ),
        ChatMessage(
            role="user",
            content=json.dumps(story_brief, ensure_ascii=False, sort_keys=True),
        ),
    ]
    llm_request = gateway.request_for_purpose("normal_chat", messages).model_copy(
        update={
            "max_output_tokens": min(8192, max(1600, request.planned_chapter_count * 72)),
            "temperature": 0.55,
            "top_p": 0.88,
            "response_format": "json",
            "stream": False,
        }
    )
    try:
        response = await gateway.generate(gateway.normalize_request(llm_request))
        parsed = StoryRoadmapDraft.model_validate_json(response.text)
        return PlannedRoadmap(
            draft=validate_provider_roadmap(
                parsed,
                expected_chapter_count=request.planned_chapter_count,
            ),
            source="provider",
        )
    except QuotaExceededError:
        raise
    except Exception:
        return PlannedRoadmap(draft=fallback, source="deterministic_fallback")
