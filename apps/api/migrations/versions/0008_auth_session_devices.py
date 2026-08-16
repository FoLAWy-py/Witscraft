"""auth session devices

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-13 17:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("auth_sessions", sa.Column("device_name", sa.String(length=160)))
    op.add_column("auth_sessions", sa.Column("ip_address", sa.String(length=64)))
    op.add_column("auth_sessions", sa.Column("ip_region", sa.String(length=160)))
    op.add_column("auth_sessions", sa.Column("user_agent", sa.String(length=500)))


def downgrade() -> None:
    op.drop_column("auth_sessions", "user_agent")
    op.drop_column("auth_sessions", "ip_region")
    op.drop_column("auth_sessions", "ip_address")
    op.drop_column("auth_sessions", "device_name")
