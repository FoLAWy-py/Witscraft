import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.db.models import CanonFact, ModelCall, Story, StoryBranch, StoryChapter, User
from app.db.session import AsyncSessionLocal, engine as db_engine
from app.routers.workspace import update_canon_fact
from app.schemas.chat import UpdateCanonFactRequest
from app.services.canon_corrections import CanonCorrectionError, correct_canon_fact


def test_canon_correction_preserves_history_and_invalidates_only_future_branch_plan() -> None:
    async def scenario() -> None:
        user_id = uuid4()
        story_id = uuid4()
        branch_id = uuid4()
        other_branch_id = uuid4()
        fact_id = uuid4()
        try:
            async with AsyncSessionLocal() as session:
                session.add(
                    User(
                        id=user_id,
                        email=f"canon-correction-{uuid4().hex}@example.invalid",
                        display_name="Canon correction test",
                        email_verified_at=datetime.now(timezone.utc),
                    )
                )
                await session.flush()
                story = Story(
                    id=story_id,
                    user_id=user_id,
                    title="Correction story",
                    status="active",
                    planned_chapter_count=5,
                    prose_language="zh-CN",
                )
                session.add(story)
                await session.flush()
                session.add_all(
                    [
                        StoryBranch(
                            id=branch_id,
                            story_id=story_id,
                            name="main",
                            version=7,
                            roadmap_version=3,
                            roadmap_source="provider",
                            ending_title="旧结局",
                        ),
                        StoryBranch(
                            id=other_branch_id,
                            story_id=story_id,
                            name="other",
                            version=2,
                            roadmap_version=2,
                            roadmap_source="provider",
                            ending_title="另一结局",
                        ),
                    ]
                )
                await session.flush()
                story.current_branch_id = branch_id
                session.add_all(
                    StoryChapter(
                        story_id=story_id,
                        branch_id=branch_id,
                        chapter_number=number,
                        title=f"旧路线 {number}",
                        objective=f"旧目标 {number}",
                        status="active" if number == 1 else "planned",
                        roadmap_version=3,
                    )
                    for number in range(1, 6)
                )
                session.add_all(
                    StoryChapter(
                        story_id=story_id,
                        branch_id=other_branch_id,
                        chapter_number=number,
                        title=f"另一分支 {number}",
                        objective="保持不变",
                        status="active" if number == 1 else "planned",
                        roadmap_version=2,
                    )
                    for number in range(1, 6)
                )
                session.add(
                    CanonFact(
                        id=fact_id,
                        story_id=story_id,
                        branch_id=branch_id,
                        fact_type="llm_state_extraction",
                        content="城门始终关闭",
                        importance=7,
                    )
                )
                await session.commit()

            async with AsyncSessionLocal() as session:
                with pytest.raises(CanonCorrectionError, match="Confirm") as unconfirmed:
                    await correct_canon_fact(
                        session,
                        fact_id=fact_id,
                        user_id=user_id,
                        new_content="城门已经打开",
                        importance=8,
                        expected_content="城门始终关闭",
                        branch_id=branch_id,
                        expected_branch_version=7,
                        expected_roadmap_version=3,
                        confirmed=False,
                    )
                assert unconfirmed.value.code == "confirmation_required"
                await session.rollback()

                with pytest.raises(CanonCorrectionError) as stale:
                    await correct_canon_fact(
                        session,
                        fact_id=fact_id,
                        user_id=user_id,
                        new_content="城门已经打开",
                        importance=8,
                        expected_content="过期内容",
                        branch_id=branch_id,
                        expected_branch_version=7,
                        expected_roadmap_version=3,
                        confirmed=True,
                    )
                assert stale.value.code == "stale"
                await session.rollback()

                with pytest.raises(CanonCorrectionError) as stale_branch:
                    await correct_canon_fact(
                        session,
                        fact_id=fact_id,
                        user_id=user_id,
                        new_content="城门已经打开",
                        importance=8,
                        expected_content="城门始终关闭",
                        branch_id=branch_id,
                        expected_branch_version=6,
                        expected_roadmap_version=3,
                        confirmed=True,
                    )
                assert stale_branch.value.code == "stale"
                await session.rollback()

                with pytest.raises(CanonCorrectionError) as stale_roadmap:
                    await correct_canon_fact(
                        session,
                        fact_id=fact_id,
                        user_id=user_id,
                        new_content="城门已经打开",
                        importance=8,
                        expected_content="城门始终关闭",
                        branch_id=branch_id,
                        expected_branch_version=7,
                        expected_roadmap_version=2,
                        confirmed=True,
                    )
                assert stale_roadmap.value.code == "stale"
                await session.rollback()

                response = await update_canon_fact(
                    str(fact_id),
                    UpdateCanonFactRequest(
                        content="城门已经打开",
                        importance=8,
                        expected_content="城门始终关闭",
                        branch_id=str(branch_id),
                        branch_version=7,
                        roadmap_version=3,
                        confirm_future_invalidation=True,
                    ),
                    str(story_id),
                    session,
                    user_id,
                )
                corrected_id = next(
                    fact["id"]
                    for fact in response.canon_fact_items
                    if fact["content"] == "城门已经打开"
                )
                corrected_id = UUID(corrected_id)
                assert response.roadmap_version == 4
                assert response.ending_title == "尚待玩家推进"
                with pytest.raises(HTTPException) as inactive_edit:
                    await update_canon_fact(
                        str(fact_id),
                        UpdateCanonFactRequest(content="城门始终关闭", importance=1),
                        str(story_id),
                        session,
                        user_id,
                    )
                assert inactive_edit.value.status_code == 409

            async with AsyncSessionLocal() as session:
                old_fact = await session.get(CanonFact, fact_id)
                corrected = await session.get(CanonFact, corrected_id)
                branch = await session.get(StoryBranch, branch_id)
                other_branch = await session.get(StoryBranch, other_branch_id)
                chapters = list(
                    (
                        await session.scalars(
                            select(StoryChapter)
                            .where(StoryChapter.branch_id == branch_id)
                            .order_by(StoryChapter.chapter_number)
                        )
                    ).all()
                )
                other_chapters = list(
                    (
                        await session.scalars(
                            select(StoryChapter)
                            .where(StoryChapter.branch_id == other_branch_id)
                            .order_by(StoryChapter.chapter_number)
                        )
                    ).all()
                )
                assert old_fact is not None and not old_fact.is_active
                assert old_fact.content == "城门始终关闭"
                assert old_fact.superseded_by == corrected_id
                assert corrected is not None
                assert corrected.content == "城门已经打开"
                assert corrected.fact_type == "player_correction"
                assert corrected.importance == 8
                assert branch is not None
                assert (branch.version, branch.roadmap_version) == (8, 4)
                assert branch.roadmap_source == "deterministic_fallback"
                assert branch.ending_title == "尚待玩家推进"
                assert chapters[0].title == "旧路线 1"
                assert chapters[0].roadmap_version == 3
                assert [chapter.title for chapter in chapters[1:]] == [
                    "未定篇章·02",
                    "未定篇章·03",
                    "未定篇章·04",
                    "未定篇章·05",
                ]
                assert {chapter.roadmap_version for chapter in chapters[1:]} == {4}
                assert other_branch is not None
                assert (other_branch.version, other_branch.roadmap_version) == (2, 2)
                assert [chapter.title for chapter in other_chapters] == [
                    f"另一分支 {number}" for number in range(1, 6)
                ]
                assert (
                    await session.scalar(
                        select(func.count(ModelCall.id)).where(ModelCall.user_id == user_id)
                    )
                    or 0
                ) == 0
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
            await db_engine.dispose()

    asyncio.run(scenario())
