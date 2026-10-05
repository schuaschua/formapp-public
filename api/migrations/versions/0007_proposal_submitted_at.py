"""Submitted timestamp (Story 3.2, spine AD-8, AD-10).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-27

Adds a nullable ``submitted_at`` to ``proposal`` (expand-only, coding-style.md rule 29): every row
already there gets it null, since no proposal has ever been submitted yet -- the real
``POST /api/proposals/:id/submit`` (Story 3.3/FORM-21) is the only thing that will ever set it.
Read/list/write-enforcement land in this story (Story 3.2); the column just needs to exist first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "proposal", sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("proposal", "submitted_at")
