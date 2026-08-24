import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.db.models import Message, Story, StoryBranch, StoryChapter, StyleProfile, User
from app.db.session import AsyncSessionLocal, engine as db_engine


def test_chapter_roadmap_and_style_profile_database_contract() -> None:
    async def scenario() -> None:
        user_id = None
        profile_id = None
        story_id = None
        try:
            async with AsyncSessionLocal() as session:
                user = User(
                    email=f"chapter-schema-{uuid4()}@example.invalid",
                    display_name="Chapter Schema Player",
                    email_verified_at=datetime.now(timezone.utc),
                )
                session.add(user)
                await session.flush()
                user_id = user.id

                profile = StyleProfile(
                    user_id=user.id,
                    name="Public-domain cadence",
                    source_type="public_domain",
                    source_label="Reviewed fixture",
                    content_hash="a" * 64,
                    analysis_version="style-profile-v1",
                    language="en",
                    features={"dialogue_ratio": 0.2},
                )
                session.add(profile)
                await session.flush()
                profile_id = profile.id

                story = Story(
                    user_id=user.id,
                    title="The Planned Journey",
                    style_profile_id=profile.id,
                    planned_chapter_count=12,
                    minimum_chapter_length=1200,
                    chapter_length_unit="words",
                    prose_language="en",
                )
                session.add(story)
                await session.flush()
                story_id = story.id
                branch = StoryBranch(
                    story_id=story.id,
                    name="Main",
                    roadmap_version=1,
                    ending_title="The Last Threshold",
                )
                session.add(branch)
                await session.flush()
                story.current_branch_id = branch.id

                session.add(
                    StoryChapter(
                        story_id=story.id,
                        branch_id=branch.id,
                        chapter_number=1,
                        title="The First Door",
                        objective="Find a way inside.",
                        status="active",
                        roadmap_version=1,
                    )
                )
                await session.commit()

                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        session.add(
                            StoryChapter(
                                story_id=story.id,
                                branch_id=branch.id,
                                chapter_number=2,
                                title="A second active chapter",
                                status="active",
                                roadmap_version=1,
                            )
                        )
                        await session.flush()

                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        story.planned_chapter_count = 121
                        await session.flush()
                await session.refresh(story)
                assert story.planned_chapter_count == 12

                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        story.minimum_chapter_length = 499
                        await session.flush()
                await session.refresh(story)
                assert story.minimum_chapter_length == 1200

                other_branch = StoryBranch(story_id=story.id, name="Other", roadmap_version=1)
                session.add(other_branch)
                await session.flush()
                other_message = Message(
                    story_id=story.id,
                    branch_id=other_branch.id,
                    role="assistant",
                    content="A chapter on another branch.",
                    meta={},
                )
                session.add(other_message)
                await session.flush()
                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        session.add(
                            StoryChapter(
                                story_id=story.id,
                                branch_id=branch.id,
                                chapter_number=3,
                                title="Cross-branch corruption",
                                status="completed",
                                message_id=other_message.id,
                                completed_at=datetime.now(timezone.utc),
                            )
                        )
                        await session.flush()

                chapter = await session.scalar(
                    select(StoryChapter).where(StoryChapter.branch_id == branch.id)
                )
                assert chapter is not None
                assistant = Message(
                    story_id=story.id,
                    branch_id=branch.id,
                    chapter_id=chapter.id,
                    role="assistant",
                    content="A complete first chapter.",
                    meta={},
                )
                session.add(assistant)
                await session.flush()
                chapter.status = "completed"
                chapter.message_id = assistant.id
                chapter.completed_at = datetime.now(timezone.utc)
                session.add(
                    StoryChapter(
                        story_id=story.id,
                        branch_id=branch.id,
                        chapter_number=2,
                        title="Beyond the Door",
                        status="active",
                        roadmap_version=2,
                    )
                )
                branch.roadmap_version = 2
                await session.commit()

                raw_columns = (
                    await session.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = current_schema()
                              AND table_name = 'style_profiles'
                            """
                        )
                    )
                ).scalars()
                assert not {"raw_text", "reference_text", "content"}.intersection(raw_columns)

                await session.execute(delete(Story).where(Story.id == story.id))
                await session.commit()
                assert await session.scalar(
                    select(func.count()).select_from(StoryChapter).where(
                        StoryChapter.story_id == story_id
                    )
                ) == 0
                assert await session.get(StyleProfile, profile_id) is not None
        finally:
            if user_id is not None:
                async with AsyncSessionLocal() as session:
                    await session.execute(delete(User).where(User.id == user_id))
                    await session.commit()
            await db_engine.dispose()

    asyncio.run(scenario())
