"""The stored customers, read for the domain's ``CustomerStore`` port (Story 5.1, FORM-218, spine
AD-3, AD-13).

``customer`` has no row-level security (AD-17 covers only ``proposal``/``answer_overrides``) and
``find_customer`` searches every customer regardless of who created it (AD-13), so no
``SET LOCAL`` scope is needed here. An exact ``customer_number`` lookup is one query. Otherwise,
whichever of ``first_name``, ``last_name`` and ``date_of_birth`` are given narrow an exact,
case-insensitive SQL pass (``lower() =`` on each given name, ``EXTRACT`` on the stored date for
whichever of year/month/day are given) -- this is what keeps a first-name-only or year-only search
correct on a table bigger than the candidate band, not only the Python re-check. Only when that
exact pass returns nothing does a second, looser SQL pass run: the same date conditions plus each
given name's ``length()`` within +/-1 of the given name's own length, still no name equality --
wide enough to hand the *real* Levenshtein-distance check (:func:`domain.customers.find_customers`)
its candidates without any Postgres extension (``pg_trgm``/``fuzzystrmatch``, AD-2). Both passes are
capped at their own guard band, well above :data:`MAX_MATCHES`, purely so a large ``customer``
table is never pulled whole into the app; the domain layer still re-checks every row and re-caps
at :data:`MAX_MATCHES` -- its own docstring explains why that matters even so.
"""

from collections.abc import Sequence

from sqlalchemy import Column, Date, MetaData, Table, Text, extract, func, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncEngine

from domain.customers import MAX_MATCHES, CustomerMatch, PartialDate

_metadata = MetaData()

# A candidate band well above MAX_MATCHES: enough rows that a genuine typo or an ambiguous
# first-name-only search still finds its match in Python, without ever pulling the whole table.
_CANDIDATE_BAND = 50

# Read-side description of only the six columns `find_customer` may ever return (AD-3, FORM-218);
# the other C1-C15 columns of the table migration 0004 creates are never read here.
customer_table = Table(
    "customer",
    _metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("first_name", Text),
    Column("last_name", Text),
    Column("date_of_birth", Date),
    Column("city", Text),
    Column("customer_number", Text),
)


class SqlCustomerStore:
    """Reads `customer` rows matching a customer number, or a name and date of birth, for
    `domain.customers`."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def candidates(
        self,
        *,
        customer_number: str | None,
        first_name: str | None,
        last_name: str | None,
        date_of_birth: PartialDate | None,
    ) -> Sequence[CustomerMatch]:
        columns = customer_table.c
        select_columns = (
            columns.id,
            columns.first_name,
            columns.last_name,
            columns.date_of_birth,
            columns.city,
            columns.customer_number,
        )
        if customer_number is not None:
            query = (
                select(*select_columns)
                .where(columns.customer_number == customer_number.strip().upper())
                .limit(MAX_MATCHES)
            )
            async with self._engine.connect() as connection:
                rows = (await connection.execute(query)).all()
        else:
            date_conditions = []
            if date_of_birth is not None:
                if date_of_birth.year is not None:
                    date_conditions.append(
                        extract("year", columns.date_of_birth) == date_of_birth.year
                    )
                if date_of_birth.month is not None:
                    date_conditions.append(
                        extract("month", columns.date_of_birth) == date_of_birth.month
                    )
                if date_of_birth.day is not None:
                    date_conditions.append(
                        extract("day", columns.date_of_birth) == date_of_birth.day
                    )

            exact_conditions = list(date_conditions)
            if first_name is not None:
                exact_conditions.append(
                    func.lower(columns.first_name) == first_name.strip().lower()
                )
            if last_name is not None:
                exact_conditions.append(
                    func.lower(columns.last_name) == last_name.strip().lower()
                )
            exact_query = (
                select(*select_columns)
                .where(*exact_conditions)
                .order_by(columns.id)
                .limit(_CANDIDATE_BAND)
            )
            async with self._engine.connect() as connection:
                rows = (await connection.execute(exact_query)).all()

            if not rows:
                # The exact pass found nothing: widen to a fuzzy-candidate band (still no name
                # equality) for domain.customers.find_customers's own Levenshtein check to narrow.
                fuzzy_conditions = list(date_conditions)
                if first_name is not None:
                    fuzzy_conditions.append(
                        func.abs(func.length(columns.first_name) - len(first_name.strip()))
                        <= 1
                    )
                if last_name is not None:
                    fuzzy_conditions.append(
                        func.abs(func.length(columns.last_name) - len(last_name.strip()))
                        <= 1
                    )
                fuzzy_query = (
                    select(*select_columns)
                    .where(*fuzzy_conditions)
                    .order_by(columns.id)
                    .limit(_CANDIDATE_BAND)
                )
                async with self._engine.connect() as connection:
                    rows = (await connection.execute(fuzzy_query)).all()
        return [
            CustomerMatch(
                customer_id=row.id,
                first_name=row.first_name,
                last_name=row.last_name,
                date_of_birth=row.date_of_birth,
                city=row.city,
                customer_number=row.customer_number,
            )
            for row in rows
        ]
