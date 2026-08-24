"""Use natural multi-turn chapter pacing.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_stories_target_chapter_length", "stories", type_="check")
    op.alter_column(
        "stories",
        "target_chapter_length",
        new_column_name="minimum_chapter_length",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default="1200",
    )
    op.execute(
        "UPDATE stories SET minimum_chapter_length = LEAST(minimum_chapter_length, 1200)"
    )
    op.create_check_constraint(
        "ck_stories_minimum_chapter_length",
        "stories",
        "minimum_chapter_length BETWEEN 500 AND 5000",
    )

    op.create_unique_constraint(
        "uq_story_chapters_story_branch_id",
        "story_chapters",
        ["story_id", "branch_id", "id"],
    )
    op.add_column("messages", sa.Column("chapter_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_messages_chapter_scope",
        "messages",
        "story_chapters",
        ["story_id", "branch_id", "chapter_id"],
        ["story_id", "branch_id", "id"],
    )
    op.create_index(
        "ix_messages_story_branch_chapter",
        "messages",
        ["story_id", "branch_id", "chapter_id", "created_at"],
        unique=False,
    )
    op.execute(
        """
        UPDATE messages AS message
        SET chapter_id = chapter.id
        FROM story_chapters AS chapter
        WHERE chapter.message_id = message.id
          AND chapter.story_id = message.story_id
          AND chapter.branch_id = message.branch_id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_messages_story_branch_chapter", table_name="messages")
    op.drop_constraint("fk_messages_chapter_scope", "messages", type_="foreignkey")
    op.drop_column("messages", "chapter_id")
    op.drop_constraint(
        "uq_story_chapters_story_branch_id", "story_chapters", type_="unique"
    )

    op.drop_constraint("ck_stories_minimum_chapter_length", "stories", type_="check")
    op.alter_column(
        "stories",
        "minimum_chapter_length",
        new_column_name="target_chapter_length",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default="1800",
    )
    op.create_check_constraint(
        "ck_stories_target_chapter_length",
        "stories",
        "target_chapter_length BETWEEN 500 AND 5000",
    )
