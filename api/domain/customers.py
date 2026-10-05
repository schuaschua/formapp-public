"""Find a returning customer in chat (Story 5.1, FORM-218/CAP-10, spine AD-3, AD-13).

``find_customer`` is the only MCP surface onto ``customer`` before a match is confirmed (linking a
match is Story 5.2's ``link_customer``). AD-13 says visibility is not scoped by owner: it searches
every stored customer, whichever agent created it. AD-3 fixes its output shape to exactly six
fields (the original five plus ``customer_number``, FORM-218), capped at five rows, so nothing else
about another agent's customer ever reaches the model.

FORM-218 gives two independent ways in: an exact ``customer_number`` (its own check digit means a
mistyped one resolves to "no match" in Python, before any query runs -- see
``domain.customer_numbers``), or optional name/date-of-birth parts (:class:`PartialDate` accepts a
year alone, a year and month, or a full date). Exactly one of the two ways is tried per call
(a ``customer_number`` always wins when given); the name/date branch first tries an exact,
case-insensitive match and only falls back to a small Levenshtein-bounded name tolerance when that
finds nothing (see :func:`find_customers`'s own docstring).

The db adapter (``adapters/db/customers.py``) does the actual SQL-side narrowing -- by
``customer_number`` or by whichever date-of-birth parts are given -- with its own ``LIMIT``, since
pulling every customer into the app on every search doesn't scale; it never filters by name in SQL
(no ``pg_trgm``/``fuzzystrmatch`` extension, AD-2), leaving all name matching, exact and fuzzy, to
:func:`find_customers`. :func:`find_customers` still re-checks every candidate the store returns and
re-caps at :data:`MAX_MATCHES`, rebuilding each result from only its six allowed fields, so a future
``CustomerStore`` that filters differently, over-returns, or carries extra columns can never leak an
unmatched row or field into the reply.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from domain.customer_numbers import sequence_of

# AD-3: `find_customer` returns at most this many candidates.
MAX_MATCHES = 5

_YEAR = re.compile(r"\d{4}")
_YEAR_MONTH = re.compile(r"(\d{4})-(\d{2})")
_YEAR_MONTH_DAY = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


@dataclass(frozen=True, slots=True)
class PartialDate:
    """A date of birth known to a year, a year and month, or the full day (FORM-218): whichever
    parts are non-``None`` must match exactly; the rest are never checked."""

    year: int | None
    month: int | None
    day: int | None


def parse_partial_date(value: str) -> PartialDate | None:
    """``value`` as ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD`` -- any other shape (including an
    invalid month/day) degrades to ``None``, the same convention as every other date this server
    reads (a value that doesn't parse matches nothing, never an error)."""
    if not isinstance(value, str):
        return None
    if _YEAR.fullmatch(value):
        return PartialDate(year=int(value), month=None, day=None)
    match = _YEAR_MONTH.fullmatch(value)
    if match:
        month = int(match.group(2))
        if not 1 <= month <= 12:
            return None
        return PartialDate(year=int(match.group(1)), month=month, day=None)
    match = _YEAR_MONTH_DAY.fullmatch(value)
    if match:
        try:
            parsed = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
        return PartialDate(year=parsed.year, month=parsed.month, day=parsed.day)
    return None


@dataclass(frozen=True, slots=True)
class CustomerMatch:
    """The six fields `find_customer` may return for one candidate (AD-3, AD-13, FORM-218)."""

    customer_id: UUID
    first_name: str
    last_name: str
    date_of_birth: date
    city: str
    customer_number: str


class CustomerStore(Protocol):
    """Port to the stored customers; implemented by the db adapter."""

    async def candidates(
        self,
        *,
        customer_number: str | None,
        first_name: str | None,
        last_name: str | None,
        date_of_birth: PartialDate | None,
    ) -> Sequence[CustomerMatch]:
        """Customers that may match this search, in any order; may include a non-match or more
        than :data:`MAX_MATCHES` rows -- :func:`find_customers` is what enforces both. Exactly one
        of ``customer_number`` or the name/date-of-birth parts is ever given (never both, never
        neither) -- :func:`find_customers` is what enforces that too."""
        ...


def _date_matches(candidate: date, partial: PartialDate | None) -> bool:
    if partial is None:
        return True
    if partial.year is not None and candidate.year != partial.year:
        return False
    if partial.month is not None and candidate.month != partial.month:
        return False
    if partial.day is not None and candidate.day != partial.day:
        return False
    return True


def _exact_name(given: str | None, candidate: str) -> bool:
    return given is None or candidate.lower() == given.lower()


def _levenshtein_at_most_one(a: str, b: str) -> bool:
    """Whether ``a`` and ``b`` (already lower-cased) are the same, or one edit (insert, delete or
    substitute a single character) apart -- ``"mcbeal"``/``"macbeal"`` is one deletion apart."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) == len(longer):
        return sum(1 for x, y in zip(shorter, longer, strict=True) if x != y) <= 1
    i = j = edits = 0
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        j += 1
    return True


def _fuzzy_name(given: str | None, candidate: str) -> bool:
    return given is None or _levenshtein_at_most_one(candidate.lower(), given.lower())


def _to_match(candidate: object) -> CustomerMatch:
    """Rebuilds a match from only the six allowed fields, whatever else ``candidate`` carries."""
    return CustomerMatch(
        customer_id=candidate.customer_id,  # type: ignore[attr-defined]
        first_name=candidate.first_name,  # type: ignore[attr-defined]
        last_name=candidate.last_name,  # type: ignore[attr-defined]
        date_of_birth=candidate.date_of_birth,  # type: ignore[attr-defined]
        city=candidate.city,  # type: ignore[attr-defined]
        customer_number=candidate.customer_number,  # type: ignore[attr-defined]
    )


async def find_customers(
    store: CustomerStore,
    *,
    customer_number: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    date_of_birth: PartialDate | None = None,
) -> Sequence[CustomerMatch]:
    """At most :data:`MAX_MATCHES` candidates for a returning customer (AD-3, AD-13, FR48/FR49,
    FORM-218/CAP-10).

    ``customer_number`` wins when given: an invalid one (bad check digit, wrong shape) is never
    even queried -- it returns ``()`` before any store call, so a mistyped neighbour's number can
    never match (spec I/O matrix "Bad check digit"). A valid one is matched exactly, case- and
    whitespace-insensitively (:func:`domain.customer_numbers.sequence_of` normalizes it).

    Otherwise, whichever of ``first_name``, ``last_name`` and ``date_of_birth`` (a
    :class:`PartialDate`, any part of it) are given must all match: date parts exactly, names
    case-insensitively. If that exact search finds nothing, one more pass allows each given name a
    Levenshtein distance of at most 1 (still requiring every given date part to match exactly) --
    tried only once the exact pass comes up empty (spec Design Notes "Name similarity").

    Giving no filters at all -- no ``customer_number``, no name, no date -- returns ``()`` without
    ever calling ``store`` (spec I/O matrix "No filters at all": never a full scan).
    """
    if customer_number is not None:
        sequence = sequence_of(customer_number)
        if sequence is None:
            return ()
        rows = await store.candidates(
            customer_number=customer_number,
            first_name=None,
            last_name=None,
            date_of_birth=None,
        )
        matches = [row for row in rows if sequence_of(row.customer_number) == sequence]
        return tuple(_to_match(row) for row in matches[:MAX_MATCHES])

    if first_name is None and last_name is None and date_of_birth is None:
        return ()

    rows = await store.candidates(
        customer_number=None,
        first_name=first_name,
        last_name=last_name,
        date_of_birth=date_of_birth,
    )
    exact = [
        row
        for row in rows
        if _date_matches(row.date_of_birth, date_of_birth)
        and _exact_name(first_name, row.first_name)
        and _exact_name(last_name, row.last_name)
    ]
    if exact:
        return tuple(_to_match(row) for row in exact[:MAX_MATCHES])
    fuzzy = [
        row
        for row in rows
        if _date_matches(row.date_of_birth, date_of_birth)
        and _fuzzy_name(first_name, row.first_name)
        and _fuzzy_name(last_name, row.last_name)
    ]
    return tuple(_to_match(row) for row in fuzzy[:MAX_MATCHES])
