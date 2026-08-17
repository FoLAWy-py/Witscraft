import asyncio
from uuid import uuid4

from sqlalchemy import delete, text

from app.db.models import MemoryItem
from app.db.session import AsyncSessionLocal, engine as db_engine
from app.embedding_config import EMBEDDING_VECTOR_DIMENSIONS
from app.services.embeddings import stored_embedding


def test_pgvector_extension_column_and_round_trip() -> None:
    async def scenario() -> None:
        memory_id = uuid4()
        vector = [0.0] * EMBEDDING_VECTOR_DIMENSIONS
        vector[0] = 1.0
        try:
            async with AsyncSessionLocal() as session:
                extension_version = await session.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
                column_type = await session.scalar(
                    text(
                        """
                        SELECT format_type(attribute.atttypid, attribute.atttypmod)
                        FROM pg_attribute AS attribute
                        JOIN pg_class AS relation ON relation.oid = attribute.attrelid
                        WHERE relation.relname = 'memory_items'
                          AND attribute.attname = 'embedding_vector'
                          AND NOT attribute.attisdropped
                        """
                    )
                )
                assert extension_version is not None
                assert column_type == f"vector({EMBEDDING_VECTOR_DIMENSIONS})"

                session.add(
                    MemoryItem(
                        id=memory_id,
                        memory_type="pgvector_contract",
                        content="fixed-dimension vector round trip",
                        entity_tags=[],
                        meta={},
                        embedding=None,
                        embedding_vector=vector,
                        embedding_dimensions=EMBEDDING_VECTOR_DIMENSIONS,
                        is_active=True,
                    )
                )
                await session.commit()

                stored = await session.get(MemoryItem, memory_id)
                assert stored is not None
                assert stored.embedding is None
                round_tripped = stored_embedding(stored)
                assert round_tripped is not None
                assert len(round_tripped) == EMBEDDING_VECTOR_DIMENSIONS
                assert round_tripped[0] == 1.0
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(MemoryItem).where(MemoryItem.id == memory_id))
                await session.commit()
            await db_engine.dispose()

    asyncio.run(scenario())
