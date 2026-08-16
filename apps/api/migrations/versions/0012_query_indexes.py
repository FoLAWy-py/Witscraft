"""Add indexes for high-frequency reads and critical foreign keys.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEXES = (
    ("ix_auth_sessions_user_created", "auth_sessions", ["user_id", sa.text("created_at DESC")], None),
    ("ix_auth_login_throttles_updated", "auth_login_throttles", ["updated_at"], None),
    (
        "ix_auth_action_tokens_user_purpose_created",
        "auth_action_tokens",
        ["user_id", "purpose", sa.text("created_at DESC")],
        None,
    ),
    ("ix_worlds_user_updated", "worlds", ["user_id", sa.text("updated_at DESC")], None),
    (
        "ix_characters_user_world_created",
        "characters",
        ["user_id", "world_id", "created_at"],
        None,
    ),
    ("ix_stories_user_updated", "stories", ["user_id", sa.text("updated_at DESC")], None),
    ("ix_stories_user_world", "stories", ["user_id", "world_id"], None),
    (
        "ix_story_branches_story_created",
        "story_branches",
        ["story_id", "created_at", "id"],
        None,
    ),
    ("ix_story_branches_parent", "story_branches", ["parent_branch_id"], None),
    (
        "ix_messages_story_branch_created",
        "messages",
        ["story_id", "branch_id", sa.text("created_at DESC"), sa.text("id DESC")],
        None,
    ),
    (
        "ix_plot_events_story_branch_created",
        "plot_events",
        ["story_id", "branch_id", "created_at", "id"],
        None,
    ),
    (
        "ix_story_state_snapshots_story_branch_created",
        "story_state_snapshots",
        ["story_id", "branch_id", sa.text("created_at DESC")],
        None,
    ),
    ("ix_story_state_snapshots_message", "story_state_snapshots", ["message_id"], None),
    (
        "ix_story_summaries_story_branch_created",
        "story_summaries",
        ["story_id", "branch_id", sa.text("created_at DESC")],
        None,
    ),
    (
        "ix_canon_facts_active_story_branch_rank",
        "canon_facts",
        ["story_id", "branch_id", sa.text("importance DESC"), sa.text("created_at DESC")],
        "is_active IS TRUE",
    ),
    ("ix_canon_facts_source_message", "canon_facts", ["source_message_id"], None),
    (
        "ix_memory_items_active_story_branch_rank",
        "memory_items",
        ["story_id", "branch_id", sa.text("importance DESC"), sa.text("updated_at DESC")],
        "is_active IS TRUE",
    ),
    ("ix_memory_items_source_message", "memory_items", ["source_message_id"], None),
    (
        "ix_model_calls_story_latest_llm",
        "model_calls",
        ["story_id", sa.text("created_at DESC")],
        "call_type = 'llm' AND status = 'succeeded'",
    ),
    ("ix_model_calls_created", "model_calls", ["created_at"], None),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, columns, predicate in INDEXES:
            op.create_index(
                name,
                table,
                columns,
                postgresql_concurrently=True,
                postgresql_where=sa.text(predicate) if predicate else None,
                if_not_exists=True,
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, _columns, _predicate in reversed(INDEXES):
            op.drop_index(
                name,
                table_name=table,
                postgresql_concurrently=True,
                if_exists=True,
            )
