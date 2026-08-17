"""Add durable memory embedding tasks.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_embedding_tasks",
        sa.Column("memory_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("story_id", sa.UUID(), nullable=True),
        sa.Column("expected_content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lease_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["memory_id"], ["memory_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'retry', 'succeeded', 'superseded', 'dead')",
            name="ck_memory_embedding_tasks_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1",
            name="ck_memory_embedding_tasks_attempts",
        ),
        sa.PrimaryKeyConstraint("memory_id"),
    )
    op.create_index(
        "ix_memory_embedding_tasks_stale_lease",
        "memory_embedding_tasks",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_memory_embedding_tasks_claim",
        "memory_embedding_tasks",
        ["status", "available_at", "created_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'retry')"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_embedding_tasks_stale_lease",
        table_name="memory_embedding_tasks",
    )
    op.drop_index("ix_memory_embedding_tasks_claim", table_name="memory_embedding_tasks")
    op.drop_table("memory_embedding_tasks")
