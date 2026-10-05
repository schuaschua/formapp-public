"""Product catalogue tables (Story 2.1).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26

Creates ``product`` and ``product_rider`` as plain reference tables that api only reads (AD-10). They
get no row-level security: AD-17 limits it to ``proposal`` and ``answer_overrides``. The seed rows
come in the data migration 0003, so a later catalogue change is one data revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Codes match the schema's P1/P2/P3 maxLength; money is numeric(12,2), read into Decimal.
CODE = sa.String(50)
NAME = sa.String(200)
MONEY = sa.Numeric(12, 2)

# The catalogue changes only by migration: take INSERT, UPDATE, DELETE and TRUNCATE from every
# grantee but the owner, including api's grants from the schema's default privileges. Grantees are
# found in the tables' ACLs, because the api principal's name differs between demo and tests.
_REVOKE_WRITES = """
DO $$
DECLARE
    grant_row record;
BEGIN
    FOR grant_row IN
        SELECT DISTINCT c.relname, acl.grantee
        FROM pg_class AS c
        CROSS JOIN LATERAL aclexplode(c.relacl) AS acl
        WHERE c.relnamespace = 'public'::regnamespace
          AND c.relname IN ('product', 'product_rider')
          AND acl.grantee <> c.relowner
          AND acl.privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')
    LOOP
        IF grant_row.grantee = 0 THEN
            EXECUTE format(
                'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE %I FROM PUBLIC',
                grant_row.relname
            );
        ELSE
            -- regrole's text form is already a quoted identifier.
            EXECUTE format(
                'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE %I FROM %s',
                grant_row.relname,
                grant_row.grantee::regrole
            );
        END IF;
    END LOOP;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "product",
        sa.Column("code", CODE, primary_key=True),
        sa.Column("name", NAME, nullable=False),
        # N1's codes (Story 1.7).
        sa.Column("type", CODE, nullable=False),
        sa.Column("covers_dependents", sa.Boolean, nullable=False),
        # [{"code": "10_yrs", "label": "10 yrs"}, ...]; P3 answers store the code.
        sa.Column("policy_terms", postgresql.JSONB, nullable=False),
        sa.Column("sum_assured_min", MONEY, nullable=True),
        sa.Column("sum_assured_max", MONEY, nullable=True),
        sa.Column("default_sum_assured", MONEY, nullable=True),
        sa.Column("default_term", CODE, nullable=False),
        sa.Column("min_age", sa.SmallInteger, nullable=False),
        sa.Column("max_age", sa.SmallInteger, nullable=False),
        sa.Column("baseline_monthly", MONEY, nullable=False),
        sa.CheckConstraint(
            "type IN ('life', 'life_health', 'health')", name="ck_product_type"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(policy_terms) = 'array' AND jsonb_array_length(policy_terms) > 0",
            name="ck_product_policy_terms",
        ),
        # A product has no sum assured at all (CFH), or a full range with the default inside it.
        # The explicit IS NOT NULLs matter: a comparison with one NULL would pass a CHECK.
        sa.CheckConstraint(
            "(sum_assured_min IS NULL AND sum_assured_max IS NULL "
            "AND default_sum_assured IS NULL) "
            "OR (sum_assured_min IS NOT NULL AND sum_assured_max IS NOT NULL "
            "AND default_sum_assured IS NOT NULL "
            "AND sum_assured_min <= default_sum_assured "
            "AND default_sum_assured <= sum_assured_max)",
            name="ck_product_sum_assured",
        ),
        # The age bands stop at 70 (content draft, Age bands).
        sa.CheckConstraint(
            "min_age >= 0 AND max_age <= 70 AND min_age <= max_age",
            name="ck_product_ages",
        ),
        sa.CheckConstraint("baseline_monthly > 0", name="ck_product_baseline"),
        # The default term is one of the product's own terms.
        sa.CheckConstraint(
            "policy_terms @> jsonb_build_array(jsonb_build_object('code', default_term))",
            name="ck_product_default_term",
        ),
    )
    op.create_table(
        "product_rider",
        # The primary key alone, so a rider code is unique across products.
        sa.Column("code", CODE, primary_key=True),
        sa.Column(
            "product_code",
            CODE,
            sa.ForeignKey("product.code", name="fk_product_rider_product"),
            nullable=False,
        ),
        sa.Column("name", NAME, nullable=False),
        sa.Column("baseline_monthly", MONEY, nullable=False),
        sa.CheckConstraint("baseline_monthly > 0", name="ck_product_rider_baseline"),
    )
    op.create_index("ix_product_rider_product_code", "product_rider", ["product_code"])
    op.execute(_REVOKE_WRITES)


def downgrade() -> None:
    op.drop_table("product_rider")
    op.drop_table("product")
