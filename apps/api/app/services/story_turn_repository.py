"""Uncommitted persistence operations for story-turn messages."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CanonFact, MemoryItem, Message, StoryStateSnapshot


class StoryTurnRepository:
    """Stage message lifecycle changes without owning transaction boundaries."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user_message(
        self,
        story_id: UUID,
        branch_id: UUID,
        content: str,
        chapter_id: UUID | None = None,
    ) -> Message:
        message = Message(
            story_id=story_id,
            branch_id=branch_id,
            role="user",
            chapter_id=chapter_id,
            content=content,
            meta={"author": "你"},
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def upsert_partial_assistant_message(
        self,
        story_id: UUID,
        branch_id: UUID,
        partial_text: str,
        assistant_message: Message | None = None,
        chapter_id: UUID | None = None,
    ) -> Message:
        if assistant_message is None:
            assistant_message = Message(
                story_id=story_id,
                branch_id=branch_id,
                role="assistant",
                chapter_id=chapter_id,
                content=partial_text,
                meta={"author": "叙事引擎", "partial": True, "stream": True},
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(assistant_message)
            await self.session.flush()
        else:
            assistant_message.content = partial_text
            assistant_message.chapter_id = chapter_id
            assistant_message.meta = {
                "author": "叙事引擎",
                "partial": True,
                "stream": True,
            }
        return assistant_message

    async def delete_message_derivatives(self, message_id: UUID) -> None:
        await self.session.execute(
            delete(StoryStateSnapshot).where(StoryStateSnapshot.message_id == message_id)
        )
        await self.session.execute(
            delete(MemoryItem).where(MemoryItem.source_message_id == message_id)
        )
        await self.session.execute(
            delete(CanonFact).where(CanonFact.source_message_id == message_id)
        )
