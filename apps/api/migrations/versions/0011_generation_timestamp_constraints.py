"""generation timestamp constraints

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-16 14:30:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("generation_requests", "created_at", nullable=False)
    op.alter_column("generation_requests", "updated_at", nullable=False)


def downgrade() -> None:
    op.alter_column("generation_requests", "updated_at", nullable=True)
    op.alter_column("generation_requests", "created_at", nullable=True)
