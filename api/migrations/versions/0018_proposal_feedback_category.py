"""proposal_feedback: category and categorised_at (Story 7.1/FORM-237, spine AD-10, AD-17, AD-20).

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-28

Adds two nullable columns so the nightly feedback job (AD-20) can record each row's category once
it is assigned (Story 7.2) and never revisit an already-categorised row on rerun ("reruns touch only
NULL categories"). Both columns are nullable from the start (coding-style.md rule 29, expand-then-
contract): the previous api version keeps working unchanged against the new schema while a deploy is
briefly running both, and existing rows are never backfilled here -- the job categorises them.

The closed category list is the same eight values `domain/feedback_categories.py` exposes to Story
7.2, plus "No comment" for a rating with no comment (AD-20). It is written directly into the CHECK
constraint below, not imported: a migration is a historical snapshot of the schema at this point in
time (migration 0015's own convention -- see its docstring), so the domain module stays free to
change independently later behind a new migration, without silently changing what this one already
applied. A CHECK constraint on a nullable column allows NULL regardless (three-valued SQL logic), so
this never blocks the existing NULL rows or new NULL inserts -- only a non-NULL value outside the
list.

No row-level security here, same as the table itself (migration 0011's docstring): AD-17 only covers
`proposal`/`answer_overrides`, and the job reads/writes this table as the api role directly, with the
same grants migration 0011 already gave it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "proposal_feedback"
_CHECK = "ck_proposal_feedback_category"
# Frozen copy of domain/feedback_categories.py's ALL_FEEDBACK_CATEGORIES as it exists today (see
# this migration's docstring for why it is copied, not imported).
_CATEGORIES = (
    "Accuracy",
    "Understanding",
    "Product choice",
    "Speed",
    "Voice",
    "Ease of use",
    "Praise",
    "Other",
    "No comment",
)


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("category", sa.Text(), nullable=True))
    op.add_column(
        _TABLE, sa.Column("categorised_at", sa.TIMESTAMP(timezone=True), nullable=True)
    )
    values = ", ".join(f"'{category}'" for category in _CATEGORIES)
    op.create_check_constraint(_CHECK, _TABLE, f"category IN ({values})")


def downgrade() -> None:
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, "categorised_at")
    op.drop_column(_TABLE, "category")
