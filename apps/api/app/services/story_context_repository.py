"""Authorized read repository for story-generation context."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, case, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CanonFact,
    Character,
    Message,
    Story,
    StorySummary,
    UserPreference,
    World,
)


class StoryContextRepository:
    def __init__(self, session: AsyncSession, user_id: UUID):
        self.session = session
        self.user_id = user_id

    async def get_story(self, story_id: UUID) -> Story:
        result = await self.session.execute(
            select(Story).where(Story.id == story_id, Story.user_id == self.user_id).limit(1)
        )
        story = result.scalar_one_or_none()
        if story is not None:
            return story

        raise HTTPException(status_code=404, detail="Story not found")

    async def load_canon_facts(self, story_id: UUID, branch_id: UUID) -> list[str]:
        result = await self.session.execute(
            select(CanonFact)
            .where(
                CanonFact.story_id == story_id,
                CanonFact.branch_id == branch_id,
                CanonFact.is_active.is_(True),
            )
            .order_by(
                case((CanonFact.fact_type == "llm_state_extraction", 0), else_=1),
                desc(CanonFact.importance),
                desc(CanonFact.created_at),
            )
            .limit(12)
        )
        return [fact.content for fact in result.scalars().all()]

    async def load_world_context(self, story: Story) -> dict:
        if story.world_id is None:
            return {}
        world = await self.session.get(World, story.world_id)
        if world is None:
            return {}
        return {
            "name": world.name,
            "description": world.description or "",
            "genre": world.genre or "",
            "rules": world.rules,
        }

    async def load_character_context(self, story: Story) -> dict:
        if story.main_character_id is None:
            return {}
        character = await self.session.get(Character, story.main_character_id)
        if character is None:
            return {}
        persona = character.persona or {}
        return {
            "name": character.name,
            "identity": persona.get("identity", character.description or ""),
            "personality": persona.get("personality", ["冷静", "戒备", "慢热"]),
            "goal": persona.get("goal", ""),
            "secret": persona.get("secret", ""),
            "speaking_style": character.speaking_style.get("tone", ""),
            "relationship": character.relationship_to_user.get("status", ""),
        }

    async def load_user_preferences(self) -> list[str]:
        result = await self.session.execute(
            select(UserPreference)
            .where(
                UserPreference.user_id == self.user_id,
                UserPreference.is_active.is_(True),
            )
            .order_by(desc(UserPreference.strength), UserPreference.created_at.asc())
            .limit(8)
        )
        return [preference.content for preference in result.scalars().all()]

    async def load_recent_messages(
        self,
        story_id: UUID,
        branch_id: UUID,
        exclude_message_ids: set[UUID] | None = None,
        after_message_id: UUID | None = None,
    ) -> list[dict]:
        query = select(Message).where(Message.story_id == story_id, Message.branch_id == branch_id)
        if exclude_message_ids:
            query = query.where(Message.id.notin_(exclude_message_ids))
        if after_message_id is not None:
            covered_message = await self.session.get(Message, after_message_id)
            if covered_message is not None:
                query = query.where(
                    or_(
                        Message.created_at > covered_message.created_at,
                        and_(
                            Message.created_at == covered_message.created_at,
                            Message.id > covered_message.id,
                        ),
                    )
                )
        result = await self.session.execute(
            query.order_by(
                desc(Message.created_at),
                desc(Message.id),
            ).limit(10)
        )
        messages = list(reversed(result.scalars().all()))
        return [{"role": message.role, "content": message.content} for message in messages]

    async def load_latest_summary(self, story_id: UUID, branch_id: UUID) -> StorySummary | None:
        result = await self.session.execute(
            select(StorySummary)
            .where(StorySummary.story_id == story_id, StorySummary.branch_id == branch_id)
            .order_by(desc(StorySummary.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def main_character_name(self, story: Story) -> str | None:
        if story.main_character_id is None:
            return None
        character = await self.session.get(Character, story.main_character_id)
        return character.name if character is not None else None
