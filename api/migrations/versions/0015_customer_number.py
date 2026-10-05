"""customer_number: a human-readable, typo-safe customer number (Story FORM-218, CAP-10, spine
AD-13).

Revision ID: 0015
Revises: 0011
Create Date: 2026-09-27

Chained onto 0011 (the current bundled head: 0009 -> 0013 -> 0012 -> 0011) -- re-chain at merge
time if `origin/dev` moved (check `alembic heads`; FORM-222 may add 0014 first).

Expand-only (coding-style.md rule 29): adds `customer.customer_number` (nullable at first, so the
column exists before it has values), a `customer_number_seq` sequence new customers draw from at
submit time (`adapters/db/proposals.py`'s upsert calls `nextval` directly, in the same transaction
as the insert), and a unique index. Backfills migration 0013's 10 seed rows with freshly generated
numbers, each drawn from the same sequence, then makes the column NOT NULL -- every row has one
from here on, seed or submitted. No drop or rename of anything migration 0013 created.

Never adds a Postgres extension (`pg_trgm`/`fuzzystrmatch`, AD-2): the check digit and any name
similarity are plain Python (`domain/customer_numbers.py`, `domain/customers.py`), never SQL.

Review fix: this migration used to import `domain.customer_numbers.format_customer_number`
directly. Migration 0013's own convention (see its docstring) is that a migration freezes its own
copy of anything it needs from application code, never importing it, so a later change to that
code (a different check digit, a new prefix, ...) can never silently change what an old,
already-applied migration backfilled. `_format_customer_number` below is a frozen private copy of
exactly what `domain/customer_numbers.py` does today; it is never imported from here.
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The same fixed ids migration 0013 seeded, in the same order, so each seed customer gets a
# deterministic customer_number too (never gen_random_uuid()-shaped, so a downgrade or a re-run
# against the same database is predictable).
_SEED_CUSTOMER_IDS = [UUID(f"00000000-0000-4000-8000-{n:012d}") for n in range(1, 11)]

_INDEX = "ix_customer_customer_number"
_SEQUENCE = "customer_number_seq"

_PREFIX = "CUS-"
_SEQUENCE_DIGITS = 4


def _luhn_check_digit(payload: str) -> int:
    """Frozen copy of `domain/customer_numbers.py`'s `_luhn_check_digit` as it exists today (see
    this file's module docstring for why it is copied, not imported): the Luhn (mod-10) check
    digit for `payload` (a digit string), doubling every second digit counting from the right."""
    total = 0
    for index, char in enumerate(reversed(payload)):
        digit = int(char)
        if index % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return (10 - total % 10) % 10


def _format_customer_number(sequence: int) -> str:
    """Frozen copy of `domain/customer_numbers.py`'s `format_customer_number` as it exists today:
    `CUS-<sequence, zero-padded to 4 digits><Luhn check digit>`, e.g. sequence `1002` ->
    `CUS-10025`."""
    body = f"{sequence:0{_SEQUENCE_DIGITS}d}"
    return f"{_PREFIX}{body}{_luhn_check_digit(body)}"


def upgrade() -> None:
    op.add_column("customer", sa.Column("customer_number", sa.Text(), nullable=True))
    op.execute(f"CREATE SEQUENCE {_SEQUENCE} START WITH 1000")

    connection = op.get_bind()
    for customer_id in _SEED_CUSTOMER_IDS:
        sequence_value = connection.execute(
            sa.text(f"SELECT nextval('{_SEQUENCE}')")
        ).scalar_one()
        connection.execute(
            sa.text("UPDATE customer SET customer_number = :number WHERE id = :id"),
            {"number": _format_customer_number(sequence_value), "id": customer_id},
        )

    op.alter_column("customer", "customer_number", nullable=False)
    op.create_index(_INDEX, "customer", ["customer_number"], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="customer")
    op.drop_column("customer", "customer_number")
    op.execute(f"DROP SEQUENCE {_SEQUENCE}")
