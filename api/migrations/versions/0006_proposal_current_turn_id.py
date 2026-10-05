"""Proposal current turn id (Story 4.3, spine AD-4).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-27

Adds nullable ``current_turn_id`` (a uuid) to ``proposal`` (expand-only, coding-style.md rule 29):
every row already there gets it null, since no turn has bound the proposal to the AI yet. Nothing
in this story sets it in production -- Story 4.5's chat adapter does, through the domain's
``begin_turn``/``end_turn`` helper -- so a fresh proposal (Story 1.8's ``create()``) leaves it null
too, exactly like ``lock_holder``/``lock_expires_at`` before the first ``POST .../lock``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "proposal",
        sa.Column("current_turn_id", PGUUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("proposal", "current_turn_id")
