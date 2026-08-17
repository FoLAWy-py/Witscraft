"""Add fixed-dimension pgvector embedding storage.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR


revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "memory_items",
        sa.Column("embedding_vector", VECTOR(EMBEDDING_DIMENSIONS), nullable=True),
    )
    op.execute(
        f"""
        UPDATE memory_items
        SET embedding_vector = embedding::text::vector({EMBEDDING_DIMENSIONS}),
            embedding = NULL
        WHERE jsonb_typeof(embedding) = 'array'
          AND jsonb_array_length(embedding) = {EMBEDDING_DIMENSIONS}
          AND embedding_dimensions = {EMBEDDING_DIMENSIONS}
          AND NOT EXISTS (
              SELECT 1
              FROM jsonb_array_elements(embedding) AS element(value)
              WHERE jsonb_typeof(element.value) != 'number'
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE memory_items
        SET embedding = embedding_vector::text::jsonb
        WHERE embedding IS NULL
          AND embedding_vector IS NOT NULL
        """
    )
    op.drop_column("memory_items", "embedding_vector")
    # The extension is database-scoped and may be shared by other tables or applications.
    # Downgrade therefore leaves it installed.
