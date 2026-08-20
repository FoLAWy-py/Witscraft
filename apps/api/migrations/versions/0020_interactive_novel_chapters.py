"""Add chapter roadmaps and abstract style profiles.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "style_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_label", sa.String(length=220), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("analysis_version", sa.String(length=80), nullable=False),
        sa.Column("language", sa.String(length=35), nullable=False),
        sa.Column(
            "features",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source_type IN ('user_owned', 'licensed', 'public_domain')",
            name="ck_style_profiles_source_type",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_style_profiles_content_hash",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "content_hash",
            "analysis_version",
            name="uq_style_profiles_user_hash_version",
        ),
    )
    op.create_index(
        "ix_style_profiles_user_updated",
        "style_profiles",
        ["user_id", sa.text("updated_at DESC")],
        unique=False,
    )

    op.add_column("stories", sa.Column("style_profile_id", sa.UUID(), nullable=True))
    op.add_column(
        "stories",
        sa.Column("planned_chapter_count", sa.Integer(), server_default="12", nullable=False),
    )
    op.add_column(
        "stories",
        sa.Column("target_chapter_length", sa.Integer(), server_default="1800", nullable=False),
    )
    op.add_column(
        "stories",
        sa.Column(
            "chapter_length_unit",
            sa.String(length=20),
            server_default="characters",
            nullable=False,
        ),
    )
    op.add_column(
        "stories",
        sa.Column(
            "prose_language",
            sa.String(length=35),
            server_default="zh-CN",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_stories_planned_chapter_count",
        "stories",
        "planned_chapter_count BETWEEN 3 AND 120",
    )
    op.create_check_constraint(
        "ck_stories_target_chapter_length",
        "stories",
        "target_chapter_length BETWEEN 500 AND 5000",
    )
    op.create_check_constraint(
        "ck_stories_chapter_length_unit",
        "stories",
        "chapter_length_unit IN ('characters', 'words')",
    )
    op.create_foreign_key(
        "fk_stories_style_profile_id",
        "stories",
        "style_profiles",
        ["style_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_stories_style_profile", "stories", ["style_profile_id"], unique=False)

    op.add_column(
        "story_branches",
        sa.Column("roadmap_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "story_branches", sa.Column("ending_title", sa.String(length=220), nullable=True)
    )
    op.create_check_constraint(
        "ck_story_branches_roadmap_version",
        "story_branches",
        "roadmap_version >= 0",
    )
    op.create_unique_constraint(
        "uq_story_branches_story_id", "story_branches", ["story_id", "id"]
    )
    op.create_unique_constraint(
        "uq_messages_story_branch_id", "messages", ["story_id", "branch_id", "id"]
    )

    op.create_table(
        "story_chapters",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("story_id", sa.UUID(), nullable=False),
        sa.Column("branch_id", sa.UUID(), nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="planned", nullable=False),
        sa.Column("roadmap_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "chapter_number BETWEEN 1 AND 120",
            name="ck_story_chapters_number",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'completed')",
            name="ck_story_chapters_status",
        ),
        sa.CheckConstraint(
            "roadmap_version >= 1",
            name="ck_story_chapters_roadmap_version",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND message_id IS NOT NULL AND completed_at IS NOT NULL) "
            "OR (status IN ('planned', 'active') AND message_id IS NULL "
            "AND completed_at IS NULL)",
            name="ck_story_chapters_completion",
        ),
        sa.ForeignKeyConstraint(
            ["story_id", "branch_id"],
            ["story_branches.story_id", "story_branches.id"],
            name="fk_story_chapters_story_branch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["story_id", "branch_id", "message_id"],
            ["messages.story_id", "messages.branch_id", "messages.id"],
            name="fk_story_chapters_message_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "branch_id", "chapter_number", name="uq_story_chapters_branch_number"
        ),
        sa.UniqueConstraint("message_id", name="uq_story_chapters_message"),
    )
    op.create_index(
        "ix_story_chapters_story_branch_status",
        "story_chapters",
        ["story_id", "branch_id", "status", "chapter_number"],
        unique=False,
    )
    op.create_index(
        "uq_story_chapters_active_branch",
        "story_chapters",
        ["branch_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_story_chapters_active_branch", table_name="story_chapters")
    op.drop_index("ix_story_chapters_story_branch_status", table_name="story_chapters")
    op.drop_table("story_chapters")
    op.drop_constraint("uq_messages_story_branch_id", "messages", type_="unique")
    op.drop_constraint("uq_story_branches_story_id", "story_branches", type_="unique")

    op.drop_constraint(
        "ck_story_branches_roadmap_version", "story_branches", type_="check"
    )
    op.drop_column("story_branches", "ending_title")
    op.drop_column("story_branches", "roadmap_version")

    op.drop_index("ix_stories_style_profile", table_name="stories")
    op.drop_constraint("fk_stories_style_profile_id", "stories", type_="foreignkey")
    op.drop_constraint("ck_stories_chapter_length_unit", "stories", type_="check")
    op.drop_constraint("ck_stories_target_chapter_length", "stories", type_="check")
    op.drop_constraint("ck_stories_planned_chapter_count", "stories", type_="check")
    op.drop_column("stories", "prose_language")
    op.drop_column("stories", "chapter_length_unit")
    op.drop_column("stories", "target_chapter_length")
    op.drop_column("stories", "planned_chapter_count")
    op.drop_column("stories", "style_profile_id")

    op.drop_index("ix_style_profiles_user_updated", table_name="style_profiles")
    op.drop_table("style_profiles")
