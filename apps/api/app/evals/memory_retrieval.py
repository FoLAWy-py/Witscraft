from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import delete, text

from app.config import Settings
from app.db.models import MemoryItem, Story, StoryBranch, User, World
from app.db.session import AsyncSessionLocal, engine as db_engine
from app.services.embeddings import EmbeddingService
from app.services.story_engine import StoryEngine
from app.services.turn_context import TurnContext


EVAL_DIR = Path(__file__).resolve().parents[2] / "evals" / "memory_retrieval" / "v1"


@dataclass(frozen=True)
class RetrievalCase:
    id: str
    query: str
    relevant: str
    trap: str


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("At least one latency value is required")
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[min(index, len(ordered) - 1)]


def evaluate_results(
    cases: list[RetrievalCase],
    retrieved: dict[str, list[str]],
    latencies_ms: list[float],
) -> dict[str, float]:
    recall_hits = sum(case.relevant in retrieved[case.id][:8] for case in cases)
    error_hits = sum(case.trap in retrieved[case.id][:8] for case in cases)
    return {
        "recall_at_8": recall_hits / len(cases),
        "error_recall_rate": error_hits / len(cases),
        "p95_latency_ms": round(percentile(latencies_ms, 0.95), 3),
    }


async def run_evaluation() -> dict:
    cases = [RetrievalCase(**item) for item in json.loads((EVAL_DIR / "cases.json").read_text())]
    thresholds = json.loads((EVAL_DIR / "thresholds.json").read_text())
    settings = Settings(dry_run_llm=True, memory_vector_search_min_items=1)
    if settings.app_environment != "test":
        raise RuntimeError("Memory retrieval evaluation is restricted to test databases")
    if not any(marker in settings.database_name.casefold() for marker in ("test", "ci")):
        raise RuntimeError("Memory retrieval evaluation requires a test-named database")
    if thresholds["candidate_rows"] <= len(cases) * 2:
        raise RuntimeError("candidate_rows must leave room for unrelated filler memories")
    embedding_service = EmbeddingService(settings)
    user_id: UUID | None = None
    retrieved: dict[str, list[str]] = {}
    latencies_ms: list[float] = []

    try:
        async with AsyncSessionLocal() as session:
            user = User(
                email=f"memory-eval-{uuid4()}@example.invalid",
                display_name="Memory Evaluation",
                email_verified_at=datetime.now(timezone.utc),
            )
            session.add(user)
            await session.flush()
            user_id = user.id
            world = World(user_id=user.id, name="Evaluation World", rules={}, lorebook=[], tone={})
            session.add(world)
            await session.flush()
            story = Story(user_id=user.id, world_id=world.id, title="Memory Evaluation")
            session.add(story)
            await session.flush()
            branch = StoryBranch(story_id=story.id, name="Main")
            session.add(branch)
            await session.flush()
            story.current_branch_id = branch.id

            metadata = None
            for case in cases:
                vector = await embedding_service.embed(case.query)
                metadata = embedding_service.metadata(case.query, vector)
                session.add_all(
                    [
                        MemoryItem(
                            user_id=user.id,
                            story_id=story.id,
                            branch_id=branch.id,
                            memory_type="retrieval_evaluation_relevant",
                            content=case.relevant,
                            importance=10,
                            entity_tags=[],
                            meta={"case_id": case.id, "expected": "relevant"},
                            embedding_vector=vector,
                            embedding_model=metadata.model,
                            embedding_dimensions=metadata.dimensions,
                            embedding_version=metadata.version,
                            is_active=True,
                        ),
                        MemoryItem(
                            user_id=user.id,
                            story_id=story.id,
                            branch_id=branch.id,
                            memory_type="retrieval_evaluation_trap",
                            content=case.trap,
                            importance=9,
                            entity_tags=[case.query],
                            meta={"case_id": case.id, "expected": "trap"},
                            embedding_vector=[-value for value in vector],
                            embedding_model=metadata.model,
                            embedding_dimensions=metadata.dimensions,
                            embedding_version=metadata.version,
                            is_active=True,
                        ),
                    ]
                )
            await session.flush()
            if metadata is None:
                raise RuntimeError("The retrieval evaluation corpus is empty")

            filler_count = thresholds["candidate_rows"] - len(cases) * 2
            filler_vector = await embedding_service.embed("unrelated filler baseline")
            vector_literal = "[" + ",".join(str(value) for value in filler_vector) + "]"
            await session.execute(
                text(
                    """
                    INSERT INTO memory_items (
                        id, user_id, story_id, branch_id, memory_type, content,
                        importance, recency_score, entity_tags, metadata,
                        embedding_vector, embedding_model, embedding_dimensions,
                        embedding_version, is_active
                    )
                    SELECT (
                               '20000000-0000-4000-8000-'
                               || lpad(to_hex(series), 12, '0')
                           )::uuid,
                           :user_id, :story_id, :branch_id,
                           'retrieval_evaluation_filler',
                           'unrelated filler memory ' || series,
                           1, 1.0, '[]'::jsonb, '{}'::jsonb,
                           CAST(:vector AS vector(1024)),
                           :model, :dimensions, :version, TRUE
                    FROM generate_series(1, :filler_count) AS generated(series)
                    """
                ),
                {
                    "user_id": user.id,
                    "story_id": story.id,
                    "branch_id": branch.id,
                    "vector": vector_literal,
                    "model": metadata.model,
                    "dimensions": metadata.dimensions,
                    "version": metadata.version,
                    "filler_count": filler_count,
                },
            )
            await session.commit()

            engine = StoryEngine.__new__(StoryEngine)
            engine.session = session
            engine.embedding_service = embedding_service
            for iteration in range(thresholds["iterations"]):
                case = cases[iteration % len(cases)]
                engine.turn_context = TurnContext()
                started = time.perf_counter()
                result = await engine._load_memories(story.id, branch.id, case.query)
                latencies_ms.append((time.perf_counter() - started) * 1000)
                retrieved.setdefault(case.id, result)
    finally:
        if user_id is not None:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
        await db_engine.dispose()

    metrics = evaluate_results(cases, retrieved, latencies_ms)
    failures = []
    if metrics["recall_at_8"] < thresholds["min_recall_at_8"]:
        failures.append("recall_at_8 below threshold")
    if metrics["error_recall_rate"] > thresholds["max_error_recall_rate"]:
        failures.append("error_recall_rate above threshold")
    if metrics["p95_latency_ms"] > thresholds["max_p95_latency_ms"]:
        failures.append("p95_latency_ms above threshold")
    return {
        "evaluation_version": "memory-retrieval-v1",
        "evidence_kind": "synthetic_contract",
        "embedding_provider": "local",
        "candidate_rows": thresholds["candidate_rows"],
        "candidate_limit": 128,
        "result_limit": 8,
        "iterations": len(latencies_ms),
        "metrics": metrics,
        "thresholds": thresholds,
        "failures": failures,
        "passed": not failures,
    }
