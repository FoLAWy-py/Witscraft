import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from app.db.models import Message, ModelCall, Story, StoryBranch, StoryChapter, User
from app.db.session import AsyncSessionLocal, engine as db_engine
from app.schemas.chat import UpdateStoryRequest
from app.services.story_chapter_plan import ChapterPlanResizeError, resize_story_chapter_plan


def test_update_story_request_binds_count_change_to_one_loaded_roadmap() -> None:
    request = UpdateStoryRequest(
        planned_chapter_count=24,
        branch_id=str(uuid4()),
        roadmap_version=7,
    )
    assert request.planned_chapter_count == 24

    with pytest.raises(ValidationError, match="branch_id and roadmap_version"):
        UpdateStoryRequest(planned_chapter_count=24)
    with pytest.raises(ValidationError, match="only valid with planned_chapter_count"):
        UpdateStoryRequest(branch_id=str(uuid4()), roadmap_version=1)


def test_active_story_chapter_plan_resize_is_atomic_across_branches() -> None:
    async def scenario() -> None:
        user_id = None
        story_id = None
        try:
            async with AsyncSessionLocal() as session:
                user = User(
                    email=f"chapter-plan-{uuid4()}@example.invalid",
                    display_name="Chapter Plan Player",
                    email_verified_at=datetime.now(timezone.utc),
                )
                session.add(user)
                await session.flush()
                user_id = user.id
                story = Story(
                    user_id=user.id,
                    title="A Resizable Journey",
                    status="active",
                    planned_chapter_count=5,
                    prose_language="en",
                )
                session.add(story)
                await session.flush()
                story_id = story.id
                main = StoryBranch(
                    story_id=story.id,
                    name="Main",
                    roadmap_version=1,
                    roadmap_source="provider",
                    ending_title="The Main Answer",
                )
                alternate = StoryBranch(
                    story_id=story.id,
                    name="Alternate",
                    roadmap_version=1,
                    roadmap_source="provider",
                    ending_title="The Other Answer",
                )
                session.add_all([main, alternate])
                await session.flush()
                story.current_branch_id = main.id

                for branch, active_number in ((main, 2), (alternate, 3)):
                    for chapter_number in range(1, 6):
                        status = (
                            "completed"
                            if chapter_number < active_number
                            else "active"
                            if chapter_number == active_number
                            else "planned"
                        )
                        message = None
                        if status == "completed":
                            message = Message(
                                story_id=story.id,
                                branch_id=branch.id,
                                role="assistant",
                                content=f"Completed chapter {chapter_number}",
                                meta={},
                            )
                            session.add(message)
                            await session.flush()
                        session.add(
                            StoryChapter(
                                story_id=story.id,
                                branch_id=branch.id,
                                chapter_number=chapter_number,
                                title=f"{branch.name} {chapter_number}",
                                objective="Advance without deciding for the player.",
                                status=status,
                                message_id=message.id if message else None,
                                completed_at=(
                                    datetime.now(timezone.utc) if message is not None else None
                                ),
                                roadmap_version=1,
                            )
                        )
                await session.commit()

                await resize_story_chapter_plan(
                    session,
                    story_id=story.id,
                    user_id=user.id,
                    active_branch_id=main.id,
                    expected_roadmap_version=1,
                    new_chapter_count=8,
                )
                await session.commit()
                await session.refresh(story)
                await session.refresh(main)
                await session.refresh(alternate)
                assert story.planned_chapter_count == 8
                assert main.roadmap_version == alternate.roadmap_version == 2
                assert main.roadmap_source == alternate.roadmap_source == "deterministic_fallback"
                for branch in (main, alternate):
                    chapters = list(
                        (
                            await session.execute(
                                select(StoryChapter)
                                .where(StoryChapter.branch_id == branch.id)
                                .order_by(StoryChapter.chapter_number)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert [chapter.chapter_number for chapter in chapters] == list(range(1, 9))
                    assert all(chapter.status == "planned" for chapter in chapters[5:])
                    assert all(chapter.roadmap_version == 2 for chapter in chapters[5:])
                    assert len({chapter.title.casefold() for chapter in chapters}) == 8

                with pytest.raises(ChapterPlanResizeError, match="reload"):
                    await resize_story_chapter_plan(
                        session,
                        story_id=story.id,
                        user_id=user.id,
                        active_branch_id=main.id,
                        expected_roadmap_version=1,
                        new_chapter_count=7,
                    )

                with pytest.raises(ChapterPlanResizeError, match="chapter 3"):
                    await resize_story_chapter_plan(
                        session,
                        story_id=story.id,
                        user_id=user.id,
                        active_branch_id=main.id,
                        expected_roadmap_version=2,
                        new_chapter_count=2,
                    )

                await resize_story_chapter_plan(
                    session,
                    story_id=story.id,
                    user_id=user.id,
                    active_branch_id=main.id,
                    expected_roadmap_version=2,
                    new_chapter_count=3,
                )
                await session.commit()
                await session.refresh(story)
                await session.refresh(main)
                await session.refresh(alternate)
                assert story.planned_chapter_count == 3
                assert main.roadmap_version == alternate.roadmap_version == 3
                assert await session.scalar(
                    select(func.count())
                    .select_from(StoryChapter)
                    .where(StoryChapter.story_id == story.id)
                ) == 6
                assert await session.scalar(
                    select(func.count()).select_from(ModelCall).where(ModelCall.user_id == user.id)
                ) == 0

                outsider = User(
                    email=f"chapter-plan-outsider-{uuid4()}@example.invalid",
                    display_name="Outsider",
                    email_verified_at=datetime.now(timezone.utc),
                )
                session.add(outsider)
                await session.flush()
                with pytest.raises(ChapterPlanResizeError) as hidden:
                    await resize_story_chapter_plan(
                        session,
                        story_id=story.id,
                        user_id=outsider.id,
                        active_branch_id=main.id,
                        expected_roadmap_version=3,
                        new_chapter_count=4,
                    )
                assert hidden.value.code == "not_found"
                await session.rollback()
        finally:
            if user_id is not None:
                async with AsyncSessionLocal() as cleanup:
                    await cleanup.execute(delete(User).where(User.id == user_id))
                    if story_id is not None:
                        await cleanup.execute(delete(Story).where(Story.id == story_id))
                    await cleanup.commit()
            await db_engine.dispose()

    asyncio.run(scenario())
