"""story prompts and preference uniqueness

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-12 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stories", sa.Column("custom_prompt", sa.Text(), nullable=True))
    op.execute(
        sa.text(
            """
            DELETE FROM user_preferences AS older
            USING user_preferences AS newer
            WHERE older.user_id = newer.user_id
              AND older.preference_type = newer.preference_type
              AND (older.updated_at, older.id) < (newer.updated_at, newer.id)
            """
        )
    )
    op.create_unique_constraint(
        "uq_user_preferences_user_type",
        "user_preferences",
        ["user_id", "preference_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_user_preferences_user_type",
        "user_preferences",
        type_="unique",
    )
    op.drop_column("stories", "custom_prompt")
