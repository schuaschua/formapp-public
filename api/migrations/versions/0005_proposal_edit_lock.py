"""Proposal edit lock columns (Story 4.4, spine AD-16).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-27

Adds nullable ``lock_holder`` (a session id or ``"ai"``) and ``lock_expires_at`` to ``proposal``
(expand-only, coding-style.md rule 29): every row already there gets both columns null, since no
one has held its lock yet -- the first ``POST /api/proposals/:id/lock`` acquires it. Neither column
gets a default: a fresh ``proposal`` row (Story 1.8's ``create()``) leaves them null too, until the
web app's own lock call.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("proposal", sa.Column("lock_holder", sa.Text(), nullable=True))
    op.add_column(
        "proposal",
        sa.Column("lock_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("proposal", "lock_expires_at")
    op.drop_column("proposal", "lock_holder")
