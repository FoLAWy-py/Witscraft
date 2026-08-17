"""Add model route change history.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_model_route_changes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("before_routes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after_routes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("restored_change_id", sa.UUID()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["restored_change_id"],
            ["user_model_route_changes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sequence"),
    )
    op.create_index(
        "ix_user_model_route_changes_user_sequence",
        "user_model_route_changes",
        ["user_id", sa.text("sequence DESC")],
    )


def downgrade() -> None:
    op.drop_table("user_model_route_changes")
