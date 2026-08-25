import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.config import Settings
from app.db.models import (
    MemoryEmbeddingTask,
    MemoryItem,
    Message,
    Story,
    StoryBranch,
    StorySummary,
    User,
    World,
)
from app.db.session import AsyncSessionLocal, engine as db_engine
from app.schemas.llm import LLMRequest, LLMResponse
from app.services.branch_manager import clone_story_branch
from app.services.story_context_repository import StoryContextRepository
from app.services.session_summarizer import (
    SUMMARY_PROMPT_VERSION,
    SUMMARY_TRIGGER_USER_REQUESTED,
    generate_session_summary,
)


class FakeSummaryGateway:
    def __init__(self, responses: list[str]):
        self.responses = iter(responses)
        self.requests: list[LLMRequest] = []

    @staticmethod
    def request_for_purpose(purpose, messages):
        return LLMRequest(
            provider="deepinfra",
            model="summary-test-model",
            messages=messages,
            purpose=purpose,
            max_output_tokens=1800,
        )

    @staticmethod
    def normalize_request(request):
        return request

    async def generate(self, request):
        self.requests.append(request)
        return LLMResponse(
            text=next(self.responses),
            provider=request.provider,
            model=request.model,
        )


def test_cumulative_summary_lineage_is_branch_scoped_and_idempotent() -> None:
    async def scenario() -> None:
        marker = uuid4().hex
        user_id = None
        try:
            async with AsyncSessionLocal() as session:
                user = User(
                    email=f"summary-lineage-{marker}@example.invalid",
                    display_name="summary-player",
                    email_verified_at=datetime.now(timezone.utc),
                )
                session.add(user)
                await session.flush()
                user_id = user.id
                world = World(user_id=user.id, name="summary-world", rules={}, lorebook=[], tone={})
                session.add(world)
                await session.flush()
                story = Story(user_id=user.id, world_id=world.id, title="Summary Story")
                session.add(story)
                await session.flush()
                main_branch = StoryBranch(story_id=story.id, name="Main")
                other_branch = StoryBranch(story_id=story.id, name="Other")
                session.add_all([main_branch, other_branch])
                await session.flush()
                story.current_branch_id = main_branch.id

                started = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)
                message_id_base = uuid4().int & ~0xFF
                first_messages = [
                    Message(
                        id=UUID(int=message_id_base + 1),
                        story_id=story.id,
                        branch_id=main_branch.id,
                        role="user",
                        content="Mira enters the archive.",
                        meta={},
                        created_at=started,
                    ),
                    Message(
                        id=UUID(int=message_id_base + 2),
                        story_id=story.id,
                        branch_id=main_branch.id,
                        role="assistant",
                        content="The brass clock stops.",
                        meta={},
                        created_at=started,
                    ),
                ]
                session.add_all(first_messages)
                await session.commit()

                gateway = FakeSummaryGateway(
                    [
                        "- Mira entered the archive and the brass clock stopped.",
                        "- Mira entered the archive.\n- Lena revealed the clock key.",
                        "- The other branch remains outside the archive.",
                    ]
                )
                first = await generate_session_summary(session, gateway, story, main_branch)
                assert first.parent_summary_id is None
                assert first.from_message_id == first_messages[0].id
                assert first.to_message_id == first_messages[-1].id
                assert first.message_count == 2
                assert first.prompt_version == SUMMARY_PROMPT_VERSION
                assert first.provider == "deepinfra"
                assert first.model == "summary-test-model"
                assert first.trigger == SUMMARY_TRIGGER_USER_REQUESTED

                new_message = Message(
                    id=UUID(int=message_id_base + 3),
                    story_id=story.id,
                    branch_id=main_branch.id,
                    role="assistant",
                    content="Lena reveals the clock key.",
                    meta={},
                    created_at=started,
                )
                session.add(new_message)
                await session.commit()

                repository = StoryContextRepository(session, user.id)
                recent = await repository.load_recent_messages(
                    story.id,
                    main_branch.id,
                    after_message_id=first_messages[-1].id,
                )
                assert recent == [{"role": "assistant", "content": new_message.content}]

                second = await generate_session_summary(session, gateway, story, main_branch)
                assert second.parent_summary_id == first.id
                assert second.from_message_id == first_messages[0].id
                assert second.to_message_id == new_message.id
                assert second.message_count == 3
                second_input = gateway.requests[1].messages[-1].content
                assert first.content in second_input
                assert new_message.content in second_input
                assert first_messages[0].content not in second_input

                with pytest.raises(ValueError, match="No new messages"):
                    await generate_session_summary(session, gateway, story, main_branch)
                assert len(gateway.requests) == 2

                other_message = Message(
                    story_id=story.id,
                    branch_id=other_branch.id,
                    role="user",
                    content="Mira stays outside.",
                    meta={},
                    created_at=started + timedelta(seconds=3),
                )
                session.add(other_message)
                await session.commit()
                other = await generate_session_summary(session, gateway, story, other_branch)
                assert other.parent_summary_id is None
                assert other.from_message_id == other_message.id
                assert other.message_count == 1

                pending_memory = MemoryItem(
                    id=uuid4(),
                    user_id=user.id,
                    story_id=story.id,
                    branch_id=main_branch.id,
                    memory_type="branch_clone_contract",
                    content="Mira discovers an unmarked passage.",
                    entity_tags=["Mira"],
                    meta={},
                    is_active=True,
                )
                session.add(pending_memory)
                await session.commit()

                cloned_branch = await clone_story_branch(
                    session,
                    story=story,
                    source_branch=main_branch,
                    user_id=user.id,
                    name="Cloned",
                    settings=Settings(dry_run_llm=True),
                )
                await session.commit()
                cloned_summaries = list(
                    (
                        await session.execute(
                            select(StorySummary)
                            .where(StorySummary.branch_id == cloned_branch.id)
                            .order_by(StorySummary.created_at.asc(), StorySummary.id.asc())
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(cloned_summaries) == 2
                assert cloned_summaries[0].parent_summary_id is None
                assert cloned_summaries[1].parent_summary_id == cloned_summaries[0].id
                assert {summary.id for summary in cloned_summaries}.isdisjoint({first.id, second.id})
                cloned_memory = await session.scalar(
                    select(MemoryItem).where(
                        MemoryItem.branch_id == cloned_branch.id,
                        MemoryItem.content == pending_memory.content,
                    )
                )
                assert cloned_memory is not None
                embedding_task = await session.get(MemoryEmbeddingTask, cloned_memory.id)
                assert embedding_task is not None
                assert embedding_task.status == "pending"
        finally:
            if user_id is not None:
                async with AsyncSessionLocal() as cleanup:
                    await cleanup.execute(delete(User).where(User.id == user_id))
                    await cleanup.commit()
            await db_engine.dispose()

    asyncio.run(scenario())
