from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CanonFact, Story, StoryBranch, StoryChapter
from app.services.story_chapter_plan import provisional_chapter_copy


@dataclass(frozen=True)
class CanonCorrectionError(Exception):
    code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


async def correct_canon_fact(
    session: AsyncSession,
    *,
    fact_id: UUID,
    user_id: UUID,
    new_content: str,
    importance: int,
    expected_content: str,
    branch_id: UUID,
    expected_branch_version: int,
    expected_roadmap_version: int,
    confirmed: bool,
) -> CanonFact:
    """Supersede a branch-local fact and conservatively invalidate future plans."""
    fact_reference = await session.get(CanonFact, fact_id)
    if fact_reference is None:
        raise CanonCorrectionError("not_found", "Canon fact not found")

    story = await session.scalar(
        select(Story)
        .where(Story.id == fact_reference.story_id, Story.user_id == user_id)
        .with_for_update()
    )
    if story is None:
        raise CanonCorrectionError("not_found", "Canon fact not found")
    if story.status != "active":
        raise CanonCorrectionError("inactive", "Only active-story canon can be corrected")

    fact = await session.scalar(select(CanonFact).where(CanonFact.id == fact_id).with_for_update())
    if fact is None or not fact.is_active or fact.branch_id != branch_id:
        raise CanonCorrectionError("stale", "The canon fact changed; reload before correcting it")
    if fact.content != expected_content:
        raise CanonCorrectionError("stale", "The canon fact changed; reload before correcting it")

    branch = await session.scalar(
        select(StoryBranch)
        .where(StoryBranch.id == branch_id, StoryBranch.story_id == story.id)
        .with_for_update()
    )
    if branch is None:
        raise CanonCorrectionError("not_found", "Story branch not found")
    if branch.roadmap_version != expected_roadmap_version:
        raise CanonCorrectionError(
            "stale",
            "The chapter roadmap changed; reload before correcting canon",
        )
    if branch.version != expected_branch_version:
        raise CanonCorrectionError(
            "stale",
            "The story branch changed; reload before correcting canon",
        )
    if not confirmed:
        raise CanonCorrectionError(
            "confirmation_required",
            "Confirm that future chapter plans and the provisional ending will be invalidated",
        )

    duplicate = await session.scalar(
        select(CanonFact.id).where(
            CanonFact.story_id == story.id,
            CanonFact.branch_id == branch.id,
            CanonFact.is_active.is_(True),
            CanonFact.id != fact.id,
            CanonFact.content == new_content,
        )
    )
    if duplicate is not None:
        raise CanonCorrectionError("duplicate", "That canon fact is already active")

    planned_chapters = list(
        (
            await session.execute(
                select(StoryChapter)
                .where(
                    StoryChapter.story_id == story.id,
                    StoryChapter.branch_id == branch.id,
                    StoryChapter.status == "planned",
                )
                .order_by(StoryChapter.chapter_number)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    next_roadmap_version = branch.roadmap_version + 1
    for chapter in planned_chapters:
        chapter.title, chapter.objective = provisional_chapter_copy(
            chapter_number=chapter.chapter_number,
            ending_title="",
            prose_language=story.prose_language,
        )
        chapter.roadmap_version = next_roadmap_version

    corrected = CanonFact(
        id=uuid4(),
        story_id=fact.story_id,
        branch_id=fact.branch_id,
        character_id=fact.character_id,
        fact_type="player_correction",
        content=new_content,
        importance=importance,
        confidence=1.0,
        is_active=True,
    )
    session.add(corrected)
    fact.is_active = False
    fact.superseded_by = corrected.id
    branch.version += 1
    branch.roadmap_version = next_roadmap_version
    branch.roadmap_source = "deterministic_fallback"
    branch.ending_title = (
        "尚待玩家推进"
        if story.prose_language.casefold().startswith("zh")
        else "Awaiting the player's path"
    )
    await session.flush()
    return corrected
