#!/usr/bin/env python3
import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import text

from app.db.session import engine
from app.embedding_config import EMBEDDING_VECTOR_DIMENSIONS


CONTRACT_MEMORY_ID = UUID("00000000-0000-0000-0000-000000001017")


async def seed() -> None:
    vector = [0.0] * EMBEDDING_VECTOR_DIMENSIONS
    vector[0] = 1.0
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO memory_items (
                    id, memory_type, content, embedding, embedding_dimensions,
                    embedding_model, embedding_version, is_active
                ) VALUES (
                    :id, 'migration_contract', 'pgvector migration contract',
                    CAST(:embedding AS jsonb), :dimensions,
                    'openai:text-embedding-3-large', 'v2-pgvector-1024', TRUE
                )
                """
            ),
            {
                "id": CONTRACT_MEMORY_ID,
                "embedding": json.dumps(vector),
                "dimensions": EMBEDDING_VECTOR_DIMENSIONS,
            },
        )


async def verify_upgrade() -> None:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT embedding IS NULL AS legacy_cleared,
                           vector_dims(embedding_vector) AS dimensions,
                           (embedding_vector::text::jsonb ->> 0)::double precision AS first_value
                    FROM memory_items
                    WHERE id = :id
                    """
                ),
                {"id": CONTRACT_MEMORY_ID},
            )
        ).one()
        if not row.legacy_cleared:
            raise RuntimeError("Compatible legacy JSONB was not cleared after vector backfill")
        if row.dimensions != EMBEDDING_VECTOR_DIMENSIONS or row.first_value != 1.0:
            raise RuntimeError("Fixed-dimension vector backfill did not preserve values")


async def verify_downgrade() -> None:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT jsonb_array_length(embedding) AS dimensions,
                           (embedding ->> 0)::double precision AS first_value
                    FROM memory_items
                    WHERE id = :id
                    """
                ),
                {"id": CONTRACT_MEMORY_ID},
            )
        ).one()
        if row.dimensions != EMBEDDING_VECTOR_DIMENSIONS or row.first_value != 1.0:
            raise RuntimeError("Downgrade did not restore the JSONB embedding")


async def cleanup() -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM memory_items WHERE id = :id"),
            {"id": CONTRACT_MEMORY_ID},
        )


async def main(phase: str) -> None:
    try:
        await {
            "seed": seed,
            "verify-upgrade": verify_upgrade,
            "verify-downgrade": verify_downgrade,
            "cleanup": cleanup,
        }[phase]()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=("seed", "verify-upgrade", "verify-downgrade", "cleanup"),
    )
    arguments = parser.parse_args()
    asyncio.run(main(arguments.phase))
