"""Customer and proposal tables (Story 1.8).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27

Creates the only two new tables (FR45, AD-10): ``customer`` (one column per ``x-fill: db``
question) and ``proposal`` (the draft/submitted row, AD-5, AD-8). The customer columns are
hardcoded here from ``domain/customer_fields.py``'s fixed 15-column list, rather than imported,
because a migration never imports domain code. Neither table gets row-level security yet (AD-17
arrives with Story 4.3/4.9's migration) nor the lock/turn columns (Story 4.4) or ``submitted_at``
(Story 3.3); ``customer`` gets no rows here (only inserted at submit, AD-13).
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TEXT = sa.Text()
GEN_UUID = sa.text("gen_random_uuid()")

# domain/customer_fields.py's fixed x-fill: db column list (C1-C15), hardcoded so this migration
# never imports domain code: (column name, type). C2 (date_of_birth) is the only date column.
_CUSTOMER_COLUMNS: tuple[tuple[str, sa.types.TypeEngine[Any]], ...] = (
    ("first_name", TEXT),  # C1
    ("date_of_birth", sa.Date()),  # C2
    ("sex_at_birth", TEXT),  # C3
    ("country_of_origin", TEXT),  # C4
    ("country_of_residence", TEXT),  # C5
    ("id_number", TEXT),  # C6
    ("email", TEXT),  # C7
    ("mobile", TEXT),  # C8
    ("street_address", TEXT),  # C9
    ("occupation", TEXT),  # C10
    ("marital_status", TEXT),  # C11
    ("income_range", TEXT),  # C12
    ("last_name", TEXT),  # C13
    ("city", TEXT),  # C14
    ("postcode", TEXT),  # C15
)


def upgrade() -> None:
    op.create_table(
        "customer",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        *(sa.Column(name, type_, nullable=True) for name, type_ in _CUSTOMER_COLUMNS),
    )
    op.create_table(
        "proposal",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "customer_id",
            UUID,
            sa.ForeignKey("customer.id", name="fk_proposal_customer"),
            nullable=True,
        ),
        sa.Column("owner_oid", TEXT, nullable=False),
        sa.Column("owner_seq", sa.Integer, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("status", TEXT, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="0"),
        sa.Column("conversation_id", TEXT, nullable=True),
        sa.Column(
            "answers",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted')", name="ck_proposal_status"
        ),
        sa.UniqueConstraint("owner_oid", "owner_seq", name="uq_proposal_owner_seq"),
    )


def downgrade() -> None:
    op.drop_table("proposal")
    op.drop_table("customer")
