"""Add auditable story roadmap source.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "story_branches",
        sa.Column(
            "roadmap_source",
            sa.String(length=30),
            server_default="legacy",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_story_branches_roadmap_source",
        "story_branches",
        "roadmap_source IN ('provider', 'deterministic_fallback', 'legacy')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_story_branches_roadmap_source", "story_branches", type_="check")
    op.drop_column("story_branches", "roadmap_source")
