"""Add audited account-wide quota policy changes.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quota_policy_changes",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("changed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("previous_limit_tokens", sa.BigInteger(), nullable=False),
        sa.Column("limit_tokens", sa.BigInteger(), nullable=False),
        sa.Column(
            "reason",
            sa.String(length=220),
            nullable=False,
            server_default="Administrator quota policy update",
        ),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "previous_limit_tokens >= 1000",
            name="ck_quota_policy_previous_limit",
        ),
        sa.CheckConstraint("limit_tokens >= 1000", name="ck_quota_policy_limit"),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quota_policy_changes_latest",
        "quota_policy_changes",
        [sa.text("id DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_quota_policy_changes_latest", table_name="quota_policy_changes")
    op.drop_table("quota_policy_changes")
