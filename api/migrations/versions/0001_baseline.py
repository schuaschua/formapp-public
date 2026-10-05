"""Empty baseline (Story 1.3).

Revision ID: 0001
Revises:
Create Date: 2026-09-26

Creates nothing but alembic_version, owned by the migration role, so api's readiness has a head to
compare against. The first tables arrive with Story 1.8.
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
