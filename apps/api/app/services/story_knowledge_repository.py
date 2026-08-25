"""Persistence boundary for extracted story memories and canon facts."""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from uuid import UUID, uuid4

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CanonFact, MemoryItem, Story, StoryBranch
from app.services.embeddings import embedding_content_hash
from app.services.memory_embedding_tasks import new_memory_embedding_task


MEMORY_RESULT_LIMIT = 8
MEMORY_CANDIDATE_LIMIT = 128
MEMORY_ACCEPTANCE_THRESHOLD = 5
MEMORY_DUPLICATE_SIMILARITY = 0.88
MEMORY_EVENT_MARKERS = (
    "发现",
    "得知",
    "揭露",
    "确认",
    "决定",
    "承诺",
    "背叛",
    "救下",
    "死亡",
    "失踪",
    "获得",
    "拾到",
    "拿到",
    "交给",
    "失去",
    "摧毁",
    "解锁",
    "打开",
    "关闭",
    "逃离",
    "抵达",
    "离开",
    "改变",
    "成为",
    "拒绝",
    "同意",
    "袭击",
    "受伤",
    "牺牲",
    "discovers",
    "learns",
    "reveals",
    "confirms",
    "decides",
    "promises",
    "betrays",
    "rescues",
    "dies",
    "vanishes",
    "obtains",
    "loses",
    "destroys",
    "unlocks",
    "escapes",
    "arrives",
    "leaves",
)
MEMORY_CONSEQUENCE_MARKERS = (
    "因此",
    "导致",
    "从此",
    "不再",
    "首次",
    "终于",
    "永久",
    "秘密",
    "真相",
    "therefore",
    "permanently",
    "secret",
    "truth",
)


@dataclass(frozen=True)
class PreparedMemory:
    content: str
    importance: int
    entity_tags: tuple[str, ...]


class StoryKnowledgeRepository:
    """Stage extracted knowledge without owning the surrounding transaction."""

    def __init__(self, session: AsyncSession, *, embedding_task_max_attempts: int):
        self.session = session
        self.embedding_task_max_attempts = embedding_task_max_attempts

    async def prepare_extracted_knowledge(
        self,
        story: Story,
        branch: StoryBranch,
        memories: list[str],
        canon_facts: list[str],
        *,
        entity_names: list[str] | None = None,
    ) -> tuple[list[PreparedMemory], list[str]]:
        recent_memories = (
            await self.load_recent_memory_candidates(story.id, branch.id) if memories else []
        )
        comparison_memories: list[tuple[str, tuple[str, ...], MemoryItem | None]] = [
            (item.content, tuple(item.entity_tags or []), item) for item in recent_memories
        ]
        pending_memories: list[tuple[str, int, tuple[str, ...]]] = []
        for raw_memory in memories:
            memory = self.normalize_memory_text(raw_memory)
            entity_tags = self.memory_entity_tags(memory, entity_names or [])
            importance = self.memory_importance(memory, entity_tags)
            if importance < MEMORY_ACCEPTANCE_THRESHOLD:
                continue
            duplicate = next(
                (
                    existing
                    for existing_content, existing_entities, existing in comparison_memories
                    if self.memory_is_near_duplicate(
                        memory,
                        entity_tags,
                        existing_content,
                        existing_entities,
                    )
                ),
                None,
            )
            if duplicate is not None:
                self.refresh_duplicate_memory(duplicate, importance, entity_tags)
                continue
            if any(
                existing is None
                and self.memory_is_near_duplicate(
                    memory,
                    entity_tags,
                    existing_content,
                    existing_entities,
                )
                for existing_content, existing_entities, existing in comparison_memories
            ):
                continue
            if await self.memory_exists(story.id, branch.id, memory):
                continue
            pending_memories.append((memory, importance, entity_tags))
            comparison_memories.append((memory, entity_tags, None))

        pending_facts: list[str] = []
        for fact in canon_facts:
            if await self.canon_fact_exists(story.id, branch.id, fact):
                continue
            if fact not in pending_facts:
                pending_facts.append(fact)

        prepared_memories = [
            PreparedMemory(
                content=memory,
                importance=importance,
                entity_tags=entity_tags,
            )
            for memory, importance, entity_tags in pending_memories
        ]
        return prepared_memories, pending_facts

    async def load_recent_memory_candidates(
        self,
        story_id: UUID,
        branch_id: UUID,
    ) -> list[MemoryItem]:
        result = await self.session.execute(
            select(MemoryItem)
            .where(
                MemoryItem.story_id == story_id,
                MemoryItem.branch_id == branch_id,
                MemoryItem.is_active.is_(True),
            )
            .order_by(desc(MemoryItem.updated_at))
            .limit(MEMORY_CANDIDATE_LIMIT)
        )
        return list(result.scalars().all())

    def add_prepared_memories(
        self,
        story: Story,
        branch: StoryBranch,
        source_message_id: UUID,
        memories: list[PreparedMemory],
        source: str,
    ) -> list[str]:
        for memory in memories:
            row = MemoryItem(
                id=uuid4(),
                user_id=story.user_id,
                story_id=story.id,
                branch_id=branch.id,
                character_id=story.main_character_id,
                memory_type=f"{source}_state_extraction",
                content=memory.content,
                importance=memory.importance,
                entity_tags=list(memory.entity_tags),
                meta={"source": f"{source}_state_extractor"},
                source_message_id=source_message_id,
                is_active=True,
            )
            self.session.add(row)
            self.session.add(
                new_memory_embedding_task(
                    row,
                    max_attempts=self.embedding_task_max_attempts,
                )
            )
        return [memory.content for memory in memories]

    def add_prepared_canon_facts(
        self,
        story: Story,
        branch: StoryBranch,
        source_message_id: UUID,
        facts: list[str],
        source: str,
    ) -> None:
        for fact in facts:
            self.session.add(
                CanonFact(
                    story_id=story.id,
                    branch_id=branch.id,
                    character_id=story.main_character_id,
                    fact_type=f"{source}_state_extraction",
                    content=fact,
                    importance=6,
                    source_message_id=source_message_id,
                    is_active=True,
                )
            )

    async def memory_exists(self, story_id: UUID, branch_id: UUID, content: str) -> bool:
        result = await self.session.execute(
            select(MemoryItem.id)
            .where(
                MemoryItem.story_id == story_id,
                MemoryItem.branch_id == branch_id,
                or_(
                    MemoryItem.content_hash == embedding_content_hash(content),
                    MemoryItem.content_hash.is_(None),
                ),
                MemoryItem.content == content,
                MemoryItem.is_active.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def canon_fact_exists(self, story_id: UUID, branch_id: UUID, content: str) -> bool:
        result = await self.session.execute(
            select(CanonFact.id)
            .where(
                CanonFact.story_id == story_id,
                CanonFact.branch_id == branch_id,
                CanonFact.content == content,
                CanonFact.is_active.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    def normalize_memory_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip(" \t\r\n，。！？；：,.!?;:\"'`*-")

    @staticmethod
    def memory_entity_tags(content: str, entity_names: list[str]) -> tuple[str, ...]:
        normalized = content.casefold()
        return tuple(entity for entity in entity_names if entity.casefold() in normalized)

    @staticmethod
    def memory_importance(content: str, entity_tags: tuple[str, ...]) -> int:
        if not content:
            return 0
        normalized = content.casefold()
        importance = 1
        if len(content) >= 16:
            importance += 1
        if entity_tags:
            importance += 2
        if any(marker in normalized for marker in MEMORY_EVENT_MARKERS):
            importance += 3
        if any(marker in normalized for marker in MEMORY_CONSEQUENCE_MARKERS):
            importance += 1
        return min(importance, 10)

    @staticmethod
    def memory_is_near_duplicate(
        content: str,
        entity_tags: tuple[str, ...],
        existing_content: str,
        existing_entities: tuple[str, ...],
    ) -> bool:
        normalized = re.sub(r"[^\w]+", "", content.casefold())
        existing_normalized = re.sub(r"[^\w]+", "", existing_content.casefold())
        if not normalized or not existing_normalized:
            return False
        if entity_tags and existing_entities and set(entity_tags).isdisjoint(existing_entities):
            return False
        if normalized == existing_normalized:
            return True
        return (
            SequenceMatcher(None, normalized, existing_normalized).ratio()
            >= MEMORY_DUPLICATE_SIMILARITY
        )

    @staticmethod
    def refresh_duplicate_memory(
        existing: MemoryItem,
        importance: int,
        entity_tags: tuple[str, ...],
    ) -> None:
        existing.importance = max(int(existing.importance or 0), importance)
        existing.entity_tags = list(dict.fromkeys([*(existing.entity_tags or []), *entity_tags]))
        existing.recency_score = 1.0

    @staticmethod
    def merge_memory_results(existing: list[str], added: list[str]) -> list[str]:
        merged: list[str] = []
        for memory in [*added, *existing]:
            if memory and memory not in merged:
                merged.append(memory)
            if len(merged) == MEMORY_RESULT_LIMIT:
                break
        return merged
