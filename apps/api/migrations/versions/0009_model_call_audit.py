"""model call audit metadata

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-16 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("model_calls", sa.Column("turn_id", sa.UUID()))
    op.add_column("model_calls", sa.Column("request_id", sa.String(length=64)))
    op.add_column(
        "model_calls",
        sa.Column("call_type", sa.String(length=20), server_default="llm", nullable=False),
    )
    op.add_column(
        "model_calls",
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "model_calls",
        sa.Column("status", sa.String(length=20), server_default="succeeded", nullable=False),
    )
    op.add_column("model_calls", sa.Column("first_token_latency_ms", sa.Integer()))
    op.add_column(
        "model_calls",
        sa.Column("token_usage_estimated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "model_calls",
        sa.Column("cache_hit", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("model_calls", sa.Column("pricing_version", sa.String(length=80)))
    op.create_index("ix_model_calls_turn_id", "model_calls", ["turn_id"])
    op.create_index("ix_model_calls_request_id", "model_calls", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_model_calls_request_id", table_name="model_calls")
    op.drop_index("ix_model_calls_turn_id", table_name="model_calls")
    op.drop_column("model_calls", "pricing_version")
    op.drop_column("model_calls", "cache_hit")
    op.drop_column("model_calls", "token_usage_estimated")
    op.drop_column("model_calls", "first_token_latency_ms")
    op.drop_column("model_calls", "status")
    op.drop_column("model_calls", "attempt")
    op.drop_column("model_calls", "call_type")
    op.drop_column("model_calls", "request_id")
    op.drop_column("model_calls", "turn_id")
