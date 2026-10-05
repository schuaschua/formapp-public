"""proposal_feedback: the AI-rating feedback recorded at submit (Story 3.3/FORM-21, spine AD-8,
AD-10).

Revision ID: 0011
Revises: 0012
Create Date: 2026-09-27

Re-chained twice onto dev's moving head at merge time: first onto 0013 (Story 5.1's
``seed_customers``, FORM-31, itself chained off 0009) once 4.5/chat (FORM-26) landed first with no
migration of its own, then onto 0012 (Story 4.9's ``answer_overrides``, FORM-30, also chained off
0013) once that merged too. 0010 and 0008 were never created (0010 was reserved for 4.5, which
turned out not to need one).

Creates ``proposal_feedback``: one row per submitted proposal, the agent's own 1-5 rating of the
AI's help on it (spec Intent "Key finding": not a live agent call, Story 4.5 is not a dependency)
plus an optional comment. ``proposal_id`` is both the primary key and the foreign key to
``proposal.id`` -- a proposal is submitted, and so rated, at most once (AD-2, AD-8). No row-level
security here (AD-17 only covers ``proposal``/``answer_overrides``): the existing REST
``scoped(for_owner(...))`` middleware already guards every write that reaches this table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "proposal_feedback",
        sa.Column(
            "proposal_id",
            UUID,
            sa.ForeignKey("proposal.id", name="fk_proposal_feedback_proposal"),
            primary_key=True,
        ),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("given_by", sa.Text, nullable=False),
        sa.Column("at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rating BETWEEN 1 AND 5", name="ck_proposal_feedback_rating"
        ),
    )


def downgrade() -> None:
    op.drop_table("proposal_feedback")
