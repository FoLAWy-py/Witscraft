"""verified email auth tokens

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-10 22:19:17.869499
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_action_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_auth_action_tokens_purpose"),
        "auth_action_tokens",
        ["purpose"],
        unique=False,
    )
    op.create_index(
        op.f("ix_auth_action_tokens_token_hash"),
        "auth_action_tokens",
        ["token_hash"],
        unique=True,
    )
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )

    # Existing rows predate trusted identity verification. The user approved a clean auth reset.
    op.execute(sa.text("DELETE FROM users"))


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")
    op.drop_index(op.f("ix_auth_action_tokens_token_hash"), table_name="auth_action_tokens")
    op.drop_index(op.f("ix_auth_action_tokens_purpose"), table_name="auth_action_tokens")
    op.drop_table("auth_action_tokens")
