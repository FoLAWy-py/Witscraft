import math
import re
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MemoryItem
from app.services.embeddings import EmbeddingService, cosine_similarity, stored_embedding
from app.services.story_knowledge_repository import (
    MEMORY_CANDIDATE_LIMIT,
    MEMORY_RESULT_LIMIT,
)
from app.services.turn_context import TurnContext


MEMORY_VECTOR_SEARCH_MIN_ITEMS = 40


class StoryMemoryRetrievalService:
    """Read-only branch memory retrieval with one query embedding per turn."""

    def __init__(
        self,
        session: AsyncSession,
        embedding_service: EmbeddingService,
        turn_context: TurnContext,
    ) -> None:
        self.session = session
        self.embedding_service = embedding_service
        self.turn_context = turn_context

    async def load_memories(
        self, story_id: UUID, branch_id: UUID, query: str | None = None
    ) -> list[str]:
        normalized_query = (query or "").strip()
        cache_key = (story_id, branch_id, normalized_query)
        cached = self.turn_context.memory_results.get(cache_key)
        if cached is not None:
            return list(cached)

        result = await self.session.execute(
            select(MemoryItem)
            .where(
                MemoryItem.story_id == story_id,
                MemoryItem.branch_id == branch_id,
                MemoryItem.is_active.is_(True),
            )
            .order_by(desc(MemoryItem.importance), desc(MemoryItem.updated_at))
            .limit(MEMORY_CANDIDATE_LIMIT)
        )
        memories = list(result.scalars().all())
        if not memories:
            selected: list[str] = []
        elif not normalized_query:
            selected = [item.content for item in memories[:MEMORY_RESULT_LIMIT]]
        else:
            threshold = getattr(
                getattr(self.embedding_service, "settings", None),
                "memory_vector_search_min_items",
                MEMORY_VECTOR_SEARCH_MIN_ITEMS,
            )
            compatible_candidates = any(
                self.embedding_service.is_model_version_compatible(
                    model=memory.embedding_model,
                    dimensions=memory.embedding_dimensions,
                    version=memory.embedding_version,
                )
                for memory in memories
            )
            query_embedding = (
                await self.embed_query_once(normalized_query)
                if len(memories) > threshold and compatible_candidates
                else []
            )
            database_semantic_scores = (
                await self.load_database_semantic_scores(
                    story_id,
                    branch_id,
                    memories,
                    query_embedding,
                )
                if query_embedding
                else {}
            )
            recency_scores = self._memory_recency_scores(memories)
            ranked = []
            for index, memory in enumerate(memories):
                compatible = query_embedding and self.embedding_service.is_compatible(
                    model=memory.embedding_model,
                    dimensions=memory.embedding_dimensions,
                    version=memory.embedding_version,
                    vector=query_embedding,
                )
                if compatible and getattr(memory, "embedding_vector", None) is not None:
                    semantic_score = database_semantic_scores.get(memory.id, 0.0)
                elif compatible:
                    semantic_score = cosine_similarity(query_embedding, stored_embedding(memory))
                else:
                    semantic_score = 0.0
                keyword_score = self._memory_keyword_score(normalized_query, memory.content)
                entity_score = self._memory_entity_score(
                    normalized_query,
                    memory.entity_tags or [],
                )
                importance_score = min(1.0, max(0.0, float(memory.importance or 0) / 10))
                score = (
                    semantic_score * 0.55
                    + keyword_score * 0.30
                    + entity_score * 0.20
                    + importance_score * 0.20
                    + recency_scores[index] * 0.05
                )
                ranked.append((score, -index, memory))
            ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
            selected = [memory.content for _, _, memory in ranked[:MEMORY_RESULT_LIMIT]]

        self.turn_context.memory_results[cache_key] = tuple(selected)
        return selected

    async def load_database_semantic_scores(
        self,
        story_id: UUID,
        branch_id: UUID,
        memories: list[MemoryItem],
        query_embedding: list[float],
    ) -> dict[UUID, float]:
        candidates = [
            memory
            for memory in memories
            if getattr(memory, "id", None) is not None
            and getattr(memory, "embedding_vector", None) is not None
            and self.embedding_service.is_model_version_compatible(
                model=memory.embedding_model,
                dimensions=memory.embedding_dimensions,
                version=memory.embedding_version,
            )
        ]
        if not candidates:
            return {}

        contract = candidates[0]
        similarity = (1 - MemoryItem.embedding_vector.cosine_distance(query_embedding)).label(
            "semantic_score"
        )
        rows = (
            await self.session.execute(
                select(MemoryItem.id, similarity).where(
                    MemoryItem.id.in_([memory.id for memory in candidates]),
                    MemoryItem.story_id == story_id,
                    MemoryItem.branch_id == branch_id,
                    MemoryItem.is_active.is_(True),
                    MemoryItem.embedding_vector.is_not(None),
                    MemoryItem.embedding_model == contract.embedding_model,
                    MemoryItem.embedding_dimensions == contract.embedding_dimensions,
                    MemoryItem.embedding_version == contract.embedding_version,
                )
            )
        ).all()
        scores: dict[UUID, float] = {}
        for memory_id, raw_score in rows:
            if raw_score is None:
                continue
            score = float(raw_score)
            if math.isfinite(score):
                scores[memory_id] = score
        return scores

    @staticmethod
    def _memory_search_terms(value: str) -> set[str]:
        normalized = value.casefold()
        terms = set(re.findall(r"[a-z0-9_]{2,}", normalized))
        for segment in re.findall(r"[\u4e00-\u9fff]+", normalized):
            if len(segment) == 1:
                terms.add(segment)
            for size in (2, 3):
                terms.update(
                    segment[index : index + size]
                    for index in range(max(0, len(segment) - size + 1))
                )
        return terms

    @classmethod
    def _memory_keyword_score(cls, query: str, content: str) -> float:
        query_terms = cls._memory_search_terms(query)
        if not query_terms:
            return 0.0
        content_terms = cls._memory_search_terms(content)
        return len(query_terms & content_terms) / len(query_terms)

    @classmethod
    def _memory_entity_score(cls, query: str, entity_tags: list) -> float:
        normalized_query = re.sub(r"[^\w]+", "", query.casefold())
        query_terms = cls._memory_search_terms(query)
        matched = 0
        valid_tags = [str(tag).strip() for tag in entity_tags if str(tag).strip()]
        for tag in valid_tags:
            normalized_tag = re.sub(r"[^\w]+", "", tag.casefold())
            if (
                bool(normalized_query and normalized_tag)
                and (normalized_query in normalized_tag or normalized_tag in normalized_query)
            ) or query_terms & cls._memory_search_terms(tag):
                matched += 1
        return matched / len(valid_tags) if valid_tags else 0.0

    @staticmethod
    def _memory_recency_scores(memories: list[MemoryItem]) -> list[float]:
        timestamps = [
            updated_at.timestamp() if (updated_at := getattr(memory, "updated_at", None)) else None
            for memory in memories
        ]
        dated = [timestamp for timestamp in timestamps if timestamp is not None]
        oldest = min(dated) if dated else None
        newest = max(dated) if dated else None
        scores: list[float] = []
        for memory, timestamp in zip(memories, timestamps, strict=True):
            if (
                timestamp is not None
                and oldest is not None
                and newest is not None
                and newest > oldest
            ):
                scores.append((timestamp - oldest) / (newest - oldest))
            else:
                scores.append(min(1.0, max(0.0, float(memory.recency_score or 0))))
        return scores

    async def embed_query_once(self, query: str) -> list[float]:
        normalized = query.strip()
        if not normalized:
            return []
        turn_context = getattr(self, "turn_context", None)
        if turn_context is None:
            turn_context = TurnContext()
            self.turn_context = turn_context
        cache = turn_context.query_embeddings
        if normalized not in cache:
            cache[normalized] = await self.embedding_service.embed(
                normalized,
                purpose="embedding_query",
            )
        else:
            record_cache_hit = getattr(self.embedding_service, "record_cache_hit", None)
            if record_cache_hit is not None:
                await record_cache_hit(
                    normalized,
                    cache[normalized],
                    purpose="embedding_query",
                )
        return cache[normalized]
