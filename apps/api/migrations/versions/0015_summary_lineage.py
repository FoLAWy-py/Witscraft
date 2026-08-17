"""Add cumulative summary lineage and provenance.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("story_summaries", sa.Column("parent_summary_id", sa.UUID()))
    op.add_column(
        "story_summaries",
        sa.Column(
            "prompt_version",
            sa.String(length=80),
        ),
    )
    op.add_column("story_summaries", sa.Column("provider", sa.String(length=40)))
    op.add_column("story_summaries", sa.Column("model", sa.String(length=220)))
    op.add_column(
        "story_summaries",
        sa.Column(
            "trigger",
            sa.String(length=40),
        ),
    )
    op.execute(
        "UPDATE story_summaries "
        "SET prompt_version = 'legacy-v1', trigger = 'legacy'"
    )
    op.alter_column(
        "story_summaries",
        "prompt_version",
        nullable=False,
        server_default="session-summary-v2",
    )
    op.alter_column(
        "story_summaries",
        "trigger",
        nullable=False,
        server_default="user_requested",
    )
    op.create_foreign_key(
        "fk_story_summaries_parent_summary",
        "story_summaries",
        "story_summaries",
        ["parent_summary_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_story_summaries_parent_summary",
        "story_summaries",
        ["parent_summary_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_story_summaries_parent_summary", table_name="story_summaries")
    op.drop_constraint(
        "fk_story_summaries_parent_summary",
        "story_summaries",
        type_="foreignkey",
    )
    op.drop_column("story_summaries", "trigger")
    op.drop_column("story_summaries", "model")
    op.drop_column("story_summaries", "provider")
    op.drop_column("story_summaries", "prompt_version")
    op.drop_column("story_summaries", "parent_summary_id")
