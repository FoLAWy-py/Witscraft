"""Add administrator roles and weekly quota reset events.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_table(
        "quota_reset_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("reset_by_user_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.String(length=220), nullable=False),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["reset_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quota_reset_events_effective", "quota_reset_events", [sa.text("effective_at DESC")]
    )
    op.create_index("ix_model_calls_user_created", "model_calls", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_model_calls_user_created", table_name="model_calls")
    op.drop_index("ix_quota_reset_events_effective", table_name="quota_reset_events")
    op.drop_table("quota_reset_events")
    op.drop_column("users", "is_admin")
