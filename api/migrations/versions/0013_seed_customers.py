"""Seed synthetic customers (Story 5.1, NFR7, AD-13).

Revision ID: 0013
Revises: 0009
Create Date: 2026-09-27

[ASSUMPTION] Migration number 0013, chained after 0009 (the current bundled head): 0008 is
reserved for Story 3.3/FORM-21 and other in-flight lanes may land 0010-0012 first, so this
revision must be re-chained to dev's actual head (and `bundled_head()`'s test expectation updated
again) at merge time -- flagged per the spec's own instruction (`.work/briefs/FORM-31.md`).

A data migration, never run at app startup (AD-10), seeding ~10 synthetic customers so
`find_customer` (Story 5.1) has real rows to search and the demo script has a returning customer to
find. Frozen copy of the `customer` table as migration 0004 created it (its own
`_CUSTOMER_COLUMNS`), never imported from `domain/customer_fields.py`, so this migration never
follows a later schema change. Every row fills all fifteen C1-C15 columns; every value is invented
(security.md rule 1) -- fake names, obviously-synthetic (never MyKad-shaped) ID numbers, fake
emails and mobiles, and invented residents of real Malaysian cities.
"""

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_TYPE = postgresql.UUID(as_uuid=True)
TEXT = sa.Text()

# Frozen copy of the table as migration 0004 created it (its own `_CUSTOMER_COLUMNS`, C1-C15), so
# this revision never follows a later schema change.
_customer = sa.table(
    "customer",
    sa.column("id", UUID_TYPE),
    sa.column("first_name", TEXT),  # C1
    sa.column("date_of_birth", sa.Date()),  # C2
    sa.column("sex_at_birth", TEXT),  # C3
    sa.column("country_of_origin", TEXT),  # C4
    sa.column("country_of_residence", TEXT),  # C5
    sa.column("id_number", TEXT),  # C6
    sa.column("email", TEXT),  # C7
    sa.column("mobile", TEXT),  # C8
    sa.column("street_address", TEXT),  # C9
    sa.column("occupation", TEXT),  # C10
    sa.column("marital_status", TEXT),  # C11
    sa.column("income_range", TEXT),  # C12
    sa.column("last_name", TEXT),  # C13
    sa.column("city", TEXT),  # C14
    sa.column("postcode", TEXT),  # C15
)


def _row(
    n: int,
    first_name: str,
    last_name: str,
    dob: date,
    sex: str,
    email_local: str,
    mobile_tail: str,
    street: str,
    occupation: str,
    marital_status: str,
    income_range: str,
    city: str,
    postcode: str,
) -> dict[str, Any]:
    # A fixed, readable id (not `gen_random_uuid()`) so `downgrade()` can delete exactly these rows.
    return {
        "id": UUID(f"00000000-0000-4000-8000-{n:012d}"),
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": dob,
        "sex_at_birth": sex,
        "country_of_origin": "MY",
        "country_of_residence": "MY",
        # Obviously synthetic, never a real MyKad number's date-encoded-prefix shape.
        "id_number": f"SYNTH{n:07d}",
        "email": f"{email_local}@example.test",
        "mobile": f"+601234{mobile_tail}",
        "street_address": street,
        "occupation": occupation,
        "marital_status": marital_status,
        "income_range": income_range,
        "city": city,
        "postcode": postcode,
    }


CUSTOMERS = [
    # The demo-script customer: agent/evals/scenarios/ally-particulars.json and
    # agent/tests/conftest.py's TURN_1 fixtures already use "Ally Macbeal, born 1994-11-20" as the
    # synthetic customer alice's demo asks about, so the same name and date of birth are seeded
    # here for `find_customer` to find her.
    _row(
        1,
        "Ally",
        "Macbeal",
        date(1994, 11, 20),
        "female",
        "ally.macbeal",
        "56781",
        "12 Jalan Bunga Raya",
        "Marketing Executive",
        "single",
        "30k_60k",
        "Petaling Jaya",
        "46000",
    ),
    # A similar-name pair (one letter apart, same last name), for the similarity-in-search test.
    _row(
        2,
        "Tan",
        "Wei Ming",
        date(1988, 3, 14),
        "male",
        "tan.weiming",
        "56782",
        "5 Lorong Kenanga",
        "Software Engineer",
        "married",
        "60k_100k",
        "George Town",
        "10450",
    ),
    _row(
        3,
        "Tan",
        "Wei Min",
        date(1990, 7, 22),
        "male",
        "tan.weimin",
        "56783",
        "8 Jalan Kiulu",
        "Accountant",
        "single",
        "under_30k",
        "Kota Kinabalu",
        "88000",
    ),
    _row(
        4,
        "Nurul Huda",
        "Ismail",
        date(1985, 1, 5),
        "female",
        "nurul.huda",
        "56784",
        "21 Jalan Dato",
        "Teacher",
        "married",
        "30k_60k",
        "Ipoh",
        "30450",
    ),
    _row(
        5,
        "Ravi",
        "Kumar",
        date(1979, 9, 30),
        "male",
        "ravi.kumar",
        "56785",
        "3 Jalan Wawasan",
        "Civil Engineer",
        "married",
        "over_100k",
        "Johor Bahru",
        "80000",
    ),
    _row(
        6,
        "Siti Aminah",
        "Yusof",
        date(1996, 6, 18),
        "female",
        "siti.aminah",
        "56786",
        "17 Jalan Merdeka",
        "Pharmacist",
        "single",
        "60k_100k",
        "Petaling Jaya",
        "46050",
    ),
    _row(
        7,
        "Lee",
        "Chong Wei",
        date(1982, 10, 21),
        "male",
        "lee.chongwei",
        "56787",
        "9 Lorong Cempaka",
        "Sales Executive",
        "divorced",
        "30k_60k",
        "George Town",
        "10460",
    ),
    _row(
        8,
        "Priya",
        "Devi",
        date(1993, 12, 2),
        "female",
        "priya.devi",
        "56788",
        "14 Jalan Cendana",
        "Graphic Designer",
        "single",
        "under_30k",
        "Ipoh",
        "30500",
    ),
    _row(
        9,
        "Wong",
        "Kar Yee",
        date(1975, 4, 11),
        "female",
        "wong.karyee",
        "56789",
        "2 Jalan Gaya",
        "Nurse",
        "widowed",
        "30k_60k",
        "Kota Kinabalu",
        "88100",
    ),
    _row(
        10,
        "Muhammad Faiz",
        "Zulkifli",
        date(1998, 2, 27),
        "male",
        "faiz.zulkifli",
        "56700",
        "6 Jalan Sutera",
        "Electrician",
        "single",
        "under_30k",
        "Johor Bahru",
        "80100",
    ),
]


def upgrade() -> None:
    op.bulk_insert(_customer, CUSTOMERS)


def downgrade() -> None:
    op.execute(
        _customer.delete().where(_customer.c.id.in_([row["id"] for row in CUSTOMERS]))
    )
