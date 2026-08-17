#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(API_DIR))

from app.config import get_settings  # noqa: E402
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.services.memory_embedding_tasks import (  # noqa: E402
    enqueue_incompatible_memories,
    process_memory_embedding_batch,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process durable memory embedding tasks.",
    )
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    parser.add_argument(
        "--enqueue-incompatible",
        action="store_true",
        help="Queue one bounded batch of active memories that need re-indexing.",
    )
    parser.add_argument("--batch-size", type=int, help="Override the configured batch size.")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    batch_size = args.batch_size or settings.memory_embedding_worker_batch_size
    if not 1 <= batch_size <= 500:
        raise ValueError("--batch-size must be between 1 and 500")

    if args.enqueue_incompatible:
        async with AsyncSessionLocal() as session:
            queued = await enqueue_incompatible_memories(
                session,
                settings,
                limit=batch_size,
            )
            await session.commit()
        print(json.dumps({"event": "memory_embedding_reindex_queued", "count": queued}))

    while True:
        counts = await process_memory_embedding_batch(settings, limit=batch_size)
        print(
            json.dumps(
                {
                    "event": "memory_embedding_batch_completed",
                    "claimed": sum(counts.values()),
                    "statuses": counts,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if args.once:
            return
        await asyncio.sleep(settings.memory_embedding_worker_poll_seconds)


async def main() -> None:
    try:
        await run(parse_args())
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
