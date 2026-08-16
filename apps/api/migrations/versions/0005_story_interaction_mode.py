"""story interaction mode

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-12 15:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stories",
        sa.Column(
            "interaction_mode",
            sa.String(length=20),
            nullable=False,
            server_default="choices",
        ),
    )


def downgrade() -> None:
    op.drop_column("stories", "interaction_mode")
