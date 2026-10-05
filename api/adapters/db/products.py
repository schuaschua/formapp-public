"""The stored product catalogue, read for the domain's ``ProductCatalogue`` port (Story 2.1, AD-2).

``product`` and ``product_rider`` are reference tables without row-level security (AD-17 covers only
``proposal`` and ``answer_overrides``), so no ``SET LOCAL`` scope is needed.
"""

from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import (
    Boolean,
    Column,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine

from domain.products import PolicyTerm, Product, ProductType, Rider

_metadata = MetaData()

# Read-side descriptions of the tables that migration 0002 creates.
product_table = Table(
    "product",
    _metadata,
    Column("code", String(50), primary_key=True),
    Column("name", String(200)),
    Column("type", String(50)),
    Column("covers_dependents", Boolean),
    Column("policy_terms", JSONB),
    Column("sum_assured_min", Numeric(12, 2, asdecimal=True)),
    Column("sum_assured_max", Numeric(12, 2, asdecimal=True)),
    Column("default_sum_assured", Numeric(12, 2, asdecimal=True)),
    Column("default_term", String(50)),
    Column("min_age", SmallInteger),
    Column("max_age", SmallInteger),
    Column("baseline_monthly", Numeric(12, 2, asdecimal=True)),
)
product_rider_table = Table(
    "product_rider",
    _metadata,
    Column("code", String(50), primary_key=True),
    Column("product_code", String(50)),
    Column("name", String(200)),
    Column("baseline_monthly", Numeric(12, 2, asdecimal=True)),
)


class SqlProductCatalogue:
    """Reads the catalogue with two Core selects and maps the rows to domain types."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def products(self) -> Sequence[Product]:
        riders = product_rider_table.c
        products = product_table.c
        async with self._engine.connect() as connection:
            rider_rows = (
                await connection.execute(
                    select(
                        riders.code,
                        riders.product_code,
                        riders.name,
                        riders.baseline_monthly,
                    ).order_by(riders.code)
                )
            ).all()
            product_rows = (
                await connection.execute(select(product_table).order_by(products.code))
            ).all()

        riders_by_product: dict[str, list[Rider]] = defaultdict(list)
        for row in rider_rows:
            riders_by_product[row.product_code].append(
                Rider(
                    code=row.code, name=row.name, baseline_monthly=row.baseline_monthly
                )
            )
        return [
            Product(
                code=row.code,
                name=row.name,
                type=ProductType(row.type),
                covers_dependents=row.covers_dependents,
                policy_terms=tuple(
                    PolicyTerm(code=term["code"], label=term["label"])
                    for term in row.policy_terms
                ),
                sum_assured_min=row.sum_assured_min,
                sum_assured_max=row.sum_assured_max,
                default_sum_assured=row.default_sum_assured,
                default_term=row.default_term,
                min_age=row.min_age,
                max_age=row.max_age,
                baseline_monthly=row.baseline_monthly,
                riders=tuple(riders_by_product[row.code]),
            )
            for row in product_rows
        ]
