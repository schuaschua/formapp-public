"""Seed the product catalogue (Story 2.1).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26

A data migration, never run at app startup (AD-10). The values are the synthetic Products and
Riders tables of _bmad-output/seed-content/form-content-draft.md; rider codes are R01-R13 in that
table's order.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of the tables as 0002 created them, so this revision never follows later changes.
_product = sa.table(
    "product",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
    sa.column("type", sa.String),
    sa.column("covers_dependents", sa.Boolean),
    sa.column("policy_terms", postgresql.JSONB),
    sa.column("sum_assured_min", sa.Numeric(12, 2)),
    sa.column("sum_assured_max", sa.Numeric(12, 2)),
    sa.column("default_sum_assured", sa.Numeric(12, 2)),
    sa.column("default_term", sa.String),
    sa.column("min_age", sa.SmallInteger),
    sa.column("max_age", sa.SmallInteger),
    sa.column("baseline_monthly", sa.Numeric(12, 2)),
)
_product_rider = sa.table(
    "product_rider",
    sa.column("code", sa.String),
    sa.column("product_code", sa.String),
    sa.column("name", sa.String),
    sa.column("baseline_monthly", sa.Numeric(12, 2)),
)


def _term(code: str, label: str) -> dict[str, str]:
    return {"code": code, "label": label}


def _money(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _product_row(
    code: str,
    name: str,
    type_: str,
    covers_dependents: bool,
    policy_terms: list[dict[str, str]],
    sum_assured: tuple[str, str, str] | None,
    default_term: str,
    ages: tuple[int, int],
    baseline_monthly: str,
) -> dict[str, Any]:
    minimum, maximum, default = sum_assured or (None, None, None)
    return {
        "code": code,
        "name": name,
        "type": type_,
        "covers_dependents": covers_dependents,
        "policy_terms": policy_terms,
        "sum_assured_min": _money(minimum),
        "sum_assured_max": _money(maximum),
        "default_sum_assured": _money(default),
        "default_term": default_term,
        "min_age": ages[0],
        "max_age": ages[1],
        "baseline_monthly": Decimal(baseline_monthly),
    }


PRODUCTS = [
    _product_row(
        "LT20",
        "SecureLife Term",
        "life",
        True,
        [
            _term("10_yrs", "10 yrs"),
            _term("20_yrs", "20 yrs"),
            _term("30_yrs", "30 yrs"),
        ],
        ("100000.00", "500000.00", "200000.00"),
        "20_yrs",
        (18, 60),
        "60.00",
    ),
    _product_row(
        "FSH",
        "FamilyShield Life & Health",
        "life_health",
        True,
        [_term("20_yrs", "20 yrs"), _term("30_yrs", "30 yrs")],
        ("200000.00", "600000.00", "300000.00"),
        "20_yrs",
        (18, 55),
        "160.00",
    ),
    _product_row(
        "ELH",
        "Essentials Life & Health",
        "life_health",
        False,
        [_term("10_yrs", "10 yrs"), _term("20_yrs", "20 yrs")],
        ("100000.00", "300000.00", "150000.00"),
        "10_yrs",
        (18, 60),
        "100.00",
    ),
    _product_row(
        "CFH",
        "CareFirst Health",
        "health",
        True,
        [_term("1_yr_renewable", "1 yr, renewable")],
        None,
        "1_yr_renewable",
        (18, 65),
        "45.00",
    ),
    _product_row(
        "LWL",
        "Legacy Whole Life",
        "life",
        True,
        [_term("whole_of_life", "Whole of life")],
        ("250000.00", "1000000.00", "500000.00"),
        "whole_of_life",
        (18, 70),
        "260.00",
    ),
]

RIDERS = [
    {
        "code": code,
        "product_code": product_code,
        "name": name,
        "baseline_monthly": Decimal(baseline),
    }
    for code, product_code, name, baseline in (
        ("R01", "LT20", "Critical illness", "20.00"),
        ("R02", "LT20", "Accidental death", "8.00"),
        ("R03", "LT20", "Waiver of premium", "5.00"),
        ("R04", "FSH", "Hospital cash", "15.00"),
        ("R05", "FSH", "Critical illness", "25.00"),
        ("R06", "FSH", "Child cover", "12.00"),
        ("R07", "FSH", "Maternity & newborn", "30.00"),
        ("R08", "ELH", "Hospital cash", "12.00"),
        ("R09", "ELH", "Critical illness", "20.00"),
        ("R10", "CFH", "Dental & optical", "10.00"),
        ("R11", "CFH", "Outpatient", "15.00"),
        ("R12", "LWL", "Waiver of premium", "10.00"),
        ("R13", "LWL", "Accidental death", "12.00"),
    )
]


def upgrade() -> None:
    op.bulk_insert(_product, PRODUCTS)
    op.bulk_insert(_product_rider, RIDERS)


def downgrade() -> None:
    op.execute(
        _product_rider.delete().where(
            _product_rider.c.code.in_([rider["code"] for rider in RIDERS])
        )
    )
    op.execute(
        _product.delete().where(
            _product.c.code.in_([product["code"] for product in PRODUCTS])
        )
    )
