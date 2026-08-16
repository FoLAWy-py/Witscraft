"""generation idempotency and branch versions

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-16 14:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "story_branches",
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "generation_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("story_id", sa.UUID(), nullable=False),
        sa.Column("branch_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="processing", nullable=False),
        sa.Column("expected_branch_version", sa.Integer(), nullable=False),
        sa.Column("user_message_id", sa.UUID()),
        sa.Column("assistant_message_id", sa.UUID()),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"], ["story_branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_generation_requests_user_key"),
    )
    op.create_index(
        "uq_generation_requests_processing_branch",
        "generation_requests",
        ["branch_id"],
        unique=True,
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.create_index(
        "ix_generation_requests_story_branch",
        "generation_requests",
        ["story_id", "branch_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_generation_requests_story_branch", table_name="generation_requests")
    op.drop_index("uq_generation_requests_processing_branch", table_name="generation_requests")
    op.drop_table("generation_requests")
    op.drop_column("story_branches", "version")
