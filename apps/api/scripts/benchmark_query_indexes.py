"""Measure production query shapes against a rollback-only synthetic dataset."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import engine


USER_ID = "8f290a64-f47c-4ee3-8496-35a029dadf6a"
STORY_ID = "bde7c77d-0a52-48f1-99fa-75bbb64c3e65"
BRANCH_ID = "3489268f-aab1-4ba1-ab63-a39079f7c831"
TABLES = (
    "messages",
    "story_state_snapshots",
    "memory_items",
    "canon_facts",
    "story_summaries",
    "model_calls",
)

QUERIES = {
    "recent_messages": f"""
        SELECT id, role, content, created_at
        FROM messages
        WHERE story_id = '{STORY_ID}' AND branch_id = '{BRANCH_ID}'
        ORDER BY created_at DESC, id DESC
        LIMIT 10
    """,
    "latest_story_state": f"""
        SELECT id, state, created_at
        FROM story_state_snapshots
        WHERE story_id = '{STORY_ID}' AND branch_id = '{BRANCH_ID}'
        ORDER BY created_at DESC
        LIMIT 1
    """,
    "ranked_active_memories": f"""
        SELECT id, content, importance, updated_at
        FROM memory_items
        WHERE story_id = '{STORY_ID}'
          AND branch_id = '{BRANCH_ID}'
          AND is_active IS TRUE
        ORDER BY importance DESC, updated_at DESC
        LIMIT 12
    """,
    "ranked_active_canon": f"""
        SELECT id, content, importance, created_at
        FROM canon_facts
        WHERE story_id = '{STORY_ID}'
          AND branch_id = '{BRANCH_ID}'
          AND is_active IS TRUE
        ORDER BY importance DESC, created_at DESC
        LIMIT 12
    """,
    "latest_summary": f"""
        SELECT id, content, created_at
        FROM story_summaries
        WHERE story_id = '{STORY_ID}' AND branch_id = '{BRANCH_ID}'
        ORDER BY created_at DESC
        LIMIT 1
    """,
    "latest_successful_model_call": f"""
        SELECT id, provider, model, created_at
        FROM model_calls
        WHERE story_id = '{STORY_ID}'
          AND call_type = 'llm'
          AND status = 'succeeded'
          AND purpose IN ('story_generation', 'story_generation_fallback')
        ORDER BY created_at DESC
        LIMIT 1
    """,
}


def _uuid_expression(prefix: str, value: str) -> str:
    return f"md5('{prefix}-' || ({value})::text)::uuid"


async def _execute_statements(connection: Any, sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            await connection.execute(text(statement))


async def _seed(connection: Any) -> None:
    await _execute_statements(
        connection,
        f"""
            INSERT INTO users (id, email, display_name)
            VALUES ('{USER_ID}', 'index-benchmark@example.invalid', 'Index benchmark')
            ON CONFLICT (id) DO NOTHING;

            INSERT INTO stories (id, user_id, title, status, interaction_mode, consistency_mode)
            VALUES ('{STORY_ID}', '{USER_ID}', 'Index benchmark', 'active', 'choices', 'auto')
            ON CONFLICT (id) DO NOTHING;

            INSERT INTO story_branches (id, story_id, name, version)
            SELECT
                CASE WHEN branch_number = 0 THEN '{BRANCH_ID}'::uuid
                     ELSE {_uuid_expression('benchmark-branch', 'branch_number')} END,
                '{STORY_ID}',
                'benchmark-' || branch_number,
                0
            FROM generate_series(0, 9) AS branch_number
            ON CONFLICT (id) DO NOTHING;

            UPDATE stories SET current_branch_id = '{BRANCH_ID}' WHERE id = '{STORY_ID}';
        """,
    )

    await _execute_statements(
        connection,
        f"""
            INSERT INTO messages
                (id, story_id, branch_id, role, content, token_count, metadata, created_at)
            SELECT
                {_uuid_expression('benchmark-message', 'item')},
                '{STORY_ID}',
                CASE WHEN item % 10 = 0 THEN '{BRANCH_ID}'::uuid
                     ELSE {_uuid_expression('benchmark-branch', 'item % 10')} END,
                CASE WHEN item % 2 = 0 THEN 'assistant' ELSE 'user' END,
                'Synthetic benchmark message ' || item,
                16,
                '{{}}'::jsonb,
                now() - (100000 - item) * interval '1 second'
            FROM generate_series(1, 100000) AS item;

            INSERT INTO story_state_snapshots (id, story_id, branch_id, state, created_at)
            SELECT
                {_uuid_expression('benchmark-state', 'item')},
                '{STORY_ID}',
                CASE WHEN item % 10 = 0 THEN '{BRANCH_ID}'::uuid
                     ELSE {_uuid_expression('benchmark-branch', 'item % 10')} END,
                jsonb_build_object('sequence', item),
                now() - (30000 - item) * interval '1 second'
            FROM generate_series(1, 30000) AS item;

            INSERT INTO memory_items
                (id, user_id, story_id, branch_id, memory_type, content, importance,
                 recency_score, entity_tags, metadata, is_active, created_at, updated_at)
            SELECT
                {_uuid_expression('benchmark-memory', 'item')},
                '{USER_ID}',
                '{STORY_ID}',
                CASE WHEN item % 10 = 0 THEN '{BRANCH_ID}'::uuid
                     ELSE {_uuid_expression('benchmark-branch', 'item % 10')} END,
                'event',
                'Synthetic benchmark memory ' || item,
                item % 10,
                1.0,
                '[]'::jsonb,
                '{{}}'::jsonb,
                item % 7 <> 0,
                now() - (30000 - item) * interval '1 second',
                now() - (30000 - item) * interval '1 second'
            FROM generate_series(1, 30000) AS item;

            INSERT INTO canon_facts
                (id, story_id, branch_id, fact_type, content, importance, confidence,
                 is_active, created_at, updated_at)
            SELECT
                {_uuid_expression('benchmark-canon', 'item')},
                '{STORY_ID}',
                CASE WHEN item % 10 = 0 THEN '{BRANCH_ID}'::uuid
                     ELSE {_uuid_expression('benchmark-branch', 'item % 10')} END,
                'world',
                'Synthetic benchmark canon fact ' || item,
                item % 10,
                1.0,
                item % 7 <> 0,
                now() - (30000 - item) * interval '1 second',
                now() - (30000 - item) * interval '1 second'
            FROM generate_series(1, 30000) AS item;

            INSERT INTO story_summaries
                (id, user_id, story_id, branch_id, summary_type, title, content,
                 message_count, created_at)
            SELECT
                {_uuid_expression('benchmark-summary', 'item')},
                '{USER_ID}',
                '{STORY_ID}',
                CASE WHEN item % 10 = 0 THEN '{BRANCH_ID}'::uuid
                     ELSE {_uuid_expression('benchmark-branch', 'item % 10')} END,
                'session',
                'Synthetic benchmark summary',
                'Synthetic benchmark summary ' || item,
                10,
                now() - (10000 - item) * interval '1 minute'
            FROM generate_series(1, 10000) AS item;

            INSERT INTO model_calls
                (id, user_id, story_id, call_type, provider, model, purpose, attempt,
                 status, token_usage_estimated, cache_hit, request, response, created_at)
            SELECT
                {_uuid_expression('benchmark-model-call', 'item')},
                '{USER_ID}',
                '{STORY_ID}',
                CASE WHEN item % 11 = 0 THEN 'embedding' ELSE 'llm' END,
                'benchmark',
                'benchmark-model',
                CASE WHEN item % 5 = 0 THEN 'story_generation_fallback'
                     ELSE 'story_generation' END,
                1,
                CASE WHEN item % 13 = 0 THEN 'failed' ELSE 'succeeded' END,
                false,
                false,
                '{{}}'::jsonb,
                '{{}}'::jsonb,
                now() - (30000 - item) * interval '1 second'
            FROM generate_series(1, 30000) AS item;
        """,
    )


def _node_types(plan: dict[str, Any]) -> str:
    nodes: list[str] = []

    def visit(node: dict[str, Any]) -> None:
        nodes.append(str(node["Node Type"]))
        for child in node.get("Plans", []):
            visit(child)

    visit(plan)
    return " > ".join(nodes)


async def _measure(connection: Any) -> list[dict[str, Any]]:
    await connection.execute(text(f"ANALYZE {', '.join(TABLES)}"))
    results = []
    for name, query in QUERIES.items():
        raw = await connection.scalar(
            text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}")
        )
        payload = json.loads(raw) if isinstance(raw, str) else raw
        report = payload[0]
        plan = report["Plan"]
        results.append(
            {
                "query": name,
                "execution_ms": round(float(report["Execution Time"]), 3),
                "planning_ms": round(float(report["Planning Time"]), 3),
                "returned_rows": plan["Actual Rows"],
                "plan": _node_types(plan),
            }
        )
    return results


async def _restore_statistics(tables: Iterable[str]) -> None:
    async with engine.begin() as connection:
        for table in tables:
            await connection.execute(text(f"ANALYZE {table}"))


async def main() -> None:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await _seed(connection)
            results = await _measure(connection)
        finally:
            await transaction.rollback()

    await _restore_statistics(TABLES)
    print(json.dumps({"synthetic_rows": 230000, "results": results}, indent=2))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
