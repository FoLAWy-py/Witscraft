"""Add versioned memory embedding metadata.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("memory_items", sa.Column("embedding_model", sa.String(length=220)))
    op.add_column("memory_items", sa.Column("embedding_dimensions", sa.Integer()))
    op.add_column("memory_items", sa.Column("embedding_version", sa.String(length=80)))
    op.add_column("memory_items", sa.Column("content_hash", sa.String(length=64)))
    op.add_column("memory_items", sa.Column("embedded_at", sa.DateTime(timezone=True)))
    op.execute(
        """
        UPDATE memory_items
        SET content_hash = encode(
                sha256(convert_to(btrim(regexp_replace(content, '\\s+', ' ', 'g')), 'UTF8')),
                'hex'
            ),
            embedding_model = CASE
                WHEN embedding IS NOT NULL THEN 'legacy:unversioned'
                ELSE NULL
            END,
            embedding_dimensions = CASE
                WHEN jsonb_typeof(embedding) = 'array' THEN jsonb_array_length(embedding)
                ELSE NULL
            END,
            embedding_version = CASE
                WHEN embedding IS NOT NULL THEN 'legacy-v0'
                ELSE NULL
            END,
            embedded_at = CASE
                WHEN embedding IS NOT NULL THEN updated_at
                ELSE NULL
            END
        """
    )
    op.create_index("ix_memory_items_content_hash", "memory_items", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_memory_items_content_hash", table_name="memory_items")
    op.drop_column("memory_items", "embedded_at")
    op.drop_column("memory_items", "content_hash")
    op.drop_column("memory_items", "embedding_version")
    op.drop_column("memory_items", "embedding_dimensions")
    op.drop_column("memory_items", "embedding_model")
