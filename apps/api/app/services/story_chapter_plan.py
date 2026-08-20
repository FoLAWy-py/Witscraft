from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Story, StoryBranch, StoryChapter


@dataclass(frozen=True)
class ChapterPlanResizeError(Exception):
    code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def _extension_copy(
    *,
    chapter_number: int,
    ending_title: str,
    prose_language: str,
) -> tuple[str, str]:
    ending = " ".join(ending_title.split())[:160]
    if prose_language.casefold().startswith("zh"):
        title = f"未定篇章·{chapter_number:02d}"
        objective = (
            f"根据玩家届时已经确认的剧情，把本章动态调整为通往“{ending}”的下一段压力与选择。"
            if ending
            else "根据玩家届时已经确认的剧情，动态形成下一段压力与选择。"
        )
    else:
        title = f"Unwritten Chapter {chapter_number:02d}"
        objective = (
            f"Adapt this chapter to the player's established path toward “{ending}”."
            if ending
            else "Adapt this chapter to the player's established path and next decision."
        )
    return title, objective


async def resize_story_chapter_plan(
    session: AsyncSession,
    *,
    story_id: UUID,
    user_id: UUID,
    active_branch_id: UUID,
    expected_roadmap_version: int,
    new_chapter_count: int,
) -> Story:
    """Atomically resize every branch without deleting active or accepted chapters."""
    story = await session.scalar(
        select(Story)
        .where(Story.id == story_id, Story.user_id == user_id)
        .with_for_update()
    )
    if story is None:
        raise ChapterPlanResizeError("not_found", "Story not found")
    if story.status != "active":
        raise ChapterPlanResizeError(
            "inactive",
            "Only an active story can change its planned chapter count",
        )

    branches = list(
        (
            await session.execute(
                select(StoryBranch)
                .where(StoryBranch.story_id == story.id)
                .order_by(StoryBranch.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    active_branch = next((branch for branch in branches if branch.id == active_branch_id), None)
    if active_branch is None:
        raise ChapterPlanResizeError("not_found", "Branch not found")
    if active_branch.roadmap_version != expected_roadmap_version:
        raise ChapterPlanResizeError(
            "stale",
            "The chapter roadmap changed; reload it before changing the chapter count",
        )
    if new_chapter_count == story.planned_chapter_count:
        return story

    chapter_rows = list(
        (
            await session.execute(
                select(StoryChapter)
                .where(StoryChapter.story_id == story.id)
                .order_by(StoryChapter.branch_id, StoryChapter.chapter_number)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    chapters_by_branch: dict[UUID, list[StoryChapter]] = {branch.id: [] for branch in branches}
    for chapter in chapter_rows:
        chapters_by_branch.setdefault(chapter.branch_id, []).append(chapter)

    old_count = story.planned_chapter_count
    for branch in branches:
        chapters = chapters_by_branch.get(branch.id, [])
        if [chapter.chapter_number for chapter in chapters] != list(range(1, old_count + 1)):
            raise ChapterPlanResizeError(
                "integrity",
                "A branch roadmap is incomplete; repair it before changing the chapter count",
            )
        protected_number = max(
            (
                chapter.chapter_number
                for chapter in chapters
                if chapter.status in {"active", "completed"}
            ),
            default=0,
        )
        if new_chapter_count < protected_number:
            raise ChapterPlanResizeError(
                "protected",
                f"The planned count cannot be below chapter {protected_number} on branch “{branch.name}”",
            )

    for branch in branches:
        chapters = chapters_by_branch[branch.id]
        next_version = branch.roadmap_version + 1
        if new_chapter_count < old_count:
            for chapter in chapters[new_chapter_count:]:
                if chapter.status != "planned":
                    raise ChapterPlanResizeError(
                        "protected",
                        "Only unstarted future chapters can be removed",
                    )
                await session.delete(chapter)
        else:
            existing_titles = {chapter.title.strip().casefold() for chapter in chapters}
            for chapter_number in range(old_count + 1, new_chapter_count + 1):
                title, objective = _extension_copy(
                    chapter_number=chapter_number,
                    ending_title=branch.ending_title or "",
                    prose_language=story.prose_language,
                )
                while title.casefold() in existing_titles:
                    title = f"{title} · {next_version}"
                existing_titles.add(title.casefold())
                session.add(
                    StoryChapter(
                        story_id=story.id,
                        branch_id=branch.id,
                        chapter_number=chapter_number,
                        title=title,
                        objective=objective,
                        status="planned",
                        roadmap_version=next_version,
                    )
                )
        branch.roadmap_version = next_version
        branch.roadmap_source = "deterministic_fallback"

    story.planned_chapter_count = new_chapter_count
    await session.flush()
    return story
