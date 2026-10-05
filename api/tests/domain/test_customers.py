"""Story 5.1/FORM-218: `find_customers` matches an exact customer number, or date-of-birth parts
and case-insensitive (falling back to typo-tolerant) names, capped at 5, returning only the six
allowed fields (AD-3, AD-13)."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import date

from domain.customer_numbers import format_customer_number
from domain.customers import (
    MAX_MATCHES,
    CustomerMatch,
    CustomerStore,
    PartialDate,
    find_customers,
    parse_partial_date,
)


@dataclass(frozen=True, slots=True)
class _RawCandidate:
    """A store row shaped with an extra column, standing in for "a future store that carries more
    than the six allowed fields" (see `domain/customers.py`'s module docstring)."""

    customer_id: object
    first_name: str
    last_name: str
    date_of_birth: object
    city: str
    customer_number: str
    id_number: str = (
        "SYNTH0000000"  # never one of the six fields find_customers may return
    )


class FakeStore:
    """An in-memory CustomerStore that hands back every row it holds, unfiltered and uncapped --
    so what's under test is `find_customers`'s own matching, cap and field-shape enforcement."""

    def __init__(self, rows: Sequence[object]) -> None:
        self._rows = rows
        self.calls: list[dict[str, object]] = []

    async def candidates(
        self,
        *,
        customer_number: str | None,
        first_name: str | None,
        last_name: str | None,
        date_of_birth: PartialDate | None,
    ) -> Sequence[object]:
        self.calls.append(
            {
                "customer_number": customer_number,
                "first_name": first_name,
                "last_name": last_name,
                "date_of_birth": date_of_birth,
            }
        )
        return self._rows


def _candidate(
    n: int,
    first_name: str,
    last_name: str,
    dob: date,
    city: str = "Petaling Jaya",
    customer_number: str | None = None,
) -> _RawCandidate:
    return _RawCandidate(
        customer_id=f"synthetic-{n}",
        first_name=first_name,
        last_name=last_name,
        date_of_birth=dob,
        city=city,
        customer_number=customer_number or format_customer_number(1000 + n),
    )


ALLY_DOB = date(1994, 11, 20)


def test_story_5_1_exact_name_and_full_date_match() -> None:
    store: CustomerStore = FakeStore([_candidate(1, "Ally", "Macbeal", ALLY_DOB)])

    matches = asyncio.run(
        find_customers(
            store,
            first_name="Ally",
            last_name="Macbeal",
            date_of_birth=PartialDate(1994, 11, 20),
        )
    )

    assert len(matches) == 1
    assert matches[0].first_name == "Ally"
    assert matches[0].last_name == "Macbeal"
    assert matches[0].date_of_birth == ALLY_DOB


def test_story_5_1_names_match_case_insensitively() -> None:
    store: CustomerStore = FakeStore([_candidate(1, "ALLY", "macbeal", ALLY_DOB)])

    matches = asyncio.run(
        find_customers(
            store,
            first_name="ally",
            last_name="MACBEAL",
            date_of_birth=PartialDate(1994, 11, 20),
        )
    )

    assert len(matches) == 1
    assert matches[0].first_name == "ALLY"
    assert matches[0].last_name == "macbeal"


def test_story_5_1_date_of_birth_must_match_exactly_not_partially_when_full() -> None:
    store: CustomerStore = FakeStore(
        [
            _candidate(1, "Ally", "Macbeal", date(1994, 11, 21)),  # a day off
            _candidate(2, "Ally", "Macbeal", date(1995, 11, 20)),  # a year off
        ]
    )

    matches = asyncio.run(
        find_customers(
            store,
            first_name="Ally",
            last_name="Macbeal",
            date_of_birth=PartialDate(1994, 11, 20),
        )
    )

    assert matches == ()


def test_story_5_1_no_match_returns_empty() -> None:
    store: CustomerStore = FakeStore(
        [_candidate(1, "Someone", "Else", date(1970, 1, 1))]
    )

    matches = asyncio.run(
        find_customers(
            store,
            first_name="Ally",
            last_name="Macbeal",
            date_of_birth=PartialDate(1994, 11, 20),
        )
    )

    assert matches == ()


def test_story_5_1_similar_name_rows_both_come_back() -> None:
    # Two different customers who share the same name and date of birth: an ambiguous search the
    # numbered match list exists to resolve (Story 5.1's UX).
    store: CustomerStore = FakeStore(
        [
            _candidate(1, "Tan", "Wei Ming", ALLY_DOB, city="George Town"),
            _candidate(2, "Tan", "Wei Ming", ALLY_DOB, city="Kota Kinabalu"),
        ]
    )

    matches = asyncio.run(
        find_customers(
            store,
            first_name="Tan",
            last_name="Wei Ming",
            date_of_birth=PartialDate(1994, 11, 20),
        )
    )

    assert {match.city for match in matches} == {"George Town", "Kota Kinabalu"}


def test_story_5_1_caps_at_five_even_with_more_candidates() -> None:
    store: CustomerStore = FakeStore(
        [
            _candidate(n, "Ally", "Macbeal", ALLY_DOB) for n in range(1, 8)
        ]  # 7 matching candidates
    )

    matches = asyncio.run(
        find_customers(
            store,
            first_name="Ally",
            last_name="Macbeal",
            date_of_birth=PartialDate(1994, 11, 20),
        )
    )

    assert len(matches) == MAX_MATCHES
    # Deterministic: the first five of what the store returned, in its order.
    assert [match.customer_id for match in matches] == [
        f"synthetic-{n}" for n in range(1, 6)
    ]


def test_story_5_1_returned_matches_carry_no_extra_fields() -> None:
    store: CustomerStore = FakeStore([_candidate(1, "Ally", "Macbeal", ALLY_DOB)])

    matches = asyncio.run(
        find_customers(
            store,
            first_name="Ally",
            last_name="Macbeal",
            date_of_birth=PartialDate(1994, 11, 20),
        )
    )

    names = {f.name for f in fields(matches[0])}
    assert names == {
        "customer_id",
        "first_name",
        "last_name",
        "date_of_birth",
        "city",
        "customer_number",
    }
    assert not hasattr(matches[0], "id_number")


def test_story_5_1_passes_the_search_arguments_to_the_store() -> None:
    store = FakeStore([])

    asyncio.run(
        find_customers(
            store,
            first_name="Ally",
            last_name="Macbeal",
            date_of_birth=PartialDate(1994, 11, 20),
        )
    )

    assert store.calls == [
        {
            "customer_number": None,
            "first_name": "Ally",
            "last_name": "Macbeal",
            "date_of_birth": PartialDate(1994, 11, 20),
        }
    ]


# --- FORM-218: partial name/date search -------------------------------------------------------


def test_story_218_first_name_and_year_month_unique_match() -> None:
    store: CustomerStore = FakeStore(
        [
            _candidate(1, "Ally", "Macbeal", ALLY_DOB),
            _candidate(2, "Ravi", "Kumar", date(1990, 5, 12)),
        ]
    )

    matches = asyncio.run(
        find_customers(store, first_name="ally", date_of_birth=PartialDate(1994, 11, None))
    )

    assert len(matches) == 1
    assert matches[0].first_name == "Ally"


def test_story_218_ambiguous_first_name_and_year_returns_all_matches() -> None:
    store: CustomerStore = FakeStore(
        [
            _candidate(1, "Tan", "Wei Ming", date(1990, 3, 14)),
            _candidate(2, "Tan", "Wei Min", date(1990, 7, 22)),
        ]
    )

    matches = asyncio.run(
        find_customers(store, first_name="Tan", date_of_birth=PartialDate(1990, None, None))
    )

    assert len(matches) == 2


def test_story_218_no_filters_at_all_never_calls_the_store() -> None:
    store = FakeStore([_candidate(1, "Ally", "Macbeal", ALLY_DOB)])

    matches = asyncio.run(find_customers(store))

    assert matches == ()
    assert store.calls == []


def test_story_218_close_spelling_matches_only_once_the_exact_search_finds_nothing() -> None:
    # "mcbeal" is one deletion away from the seeded "Macbeal" (spec Design Notes).
    store: CustomerStore = FakeStore([_candidate(1, "Ally", "Macbeal", ALLY_DOB)])

    matches = asyncio.run(
        find_customers(store, first_name="Ally", last_name="mcbeal")
    )

    assert len(matches) == 1
    assert matches[0].last_name == "Macbeal"


def test_story_218_fuzzy_is_never_tried_when_an_exact_match_exists() -> None:
    store: CustomerStore = FakeStore(
        [
            _candidate(1, "Ally", "Macbeal", ALLY_DOB),
            _candidate(2, "Ally", "Mcbeal", date(1994, 11, 20)),
        ]
    )

    matches = asyncio.run(find_customers(store, first_name="Ally", last_name="Macbeal"))

    assert len(matches) == 1
    assert matches[0].last_name == "Macbeal"


def test_story_218_unrelated_name_is_not_a_fuzzy_match() -> None:
    store: CustomerStore = FakeStore([_candidate(1, "Someone", "Else", ALLY_DOB)])

    matches = asyncio.run(find_customers(store, first_name="Ally", last_name="Macbeal"))

    assert matches == ()


# --- FORM-218: customer_number search ----------------------------------------------------------


def test_story_218_exact_customer_number_matches() -> None:
    number = format_customer_number(1023)
    store: CustomerStore = FakeStore(
        [_candidate(1, "Ally", "Macbeal", ALLY_DOB, customer_number=number)]
    )

    matches = asyncio.run(find_customers(store, customer_number=number))

    assert len(matches) == 1
    assert matches[0].customer_number == number


def test_story_218_altered_check_digit_never_queries_the_store() -> None:
    number = format_customer_number(1023)
    altered = number[:-1] + str((int(number[-1]) + 1) % 10)
    store = FakeStore([_candidate(1, "Ally", "Macbeal", ALLY_DOB, customer_number=number)])

    matches = asyncio.run(find_customers(store, customer_number=altered))

    assert matches == ()
    assert store.calls == []  # never even asked the store (spec I/O matrix "Bad check digit")


def test_story_218_unknown_but_valid_customer_number_finds_nothing() -> None:
    number = format_customer_number(1023)
    other = format_customer_number(1024)
    store = FakeStore([_candidate(1, "Ally", "Macbeal", ALLY_DOB, customer_number=number)])

    matches = asyncio.run(find_customers(store, customer_number=other))

    assert matches == ()


def test_story_218_customer_number_search_ignores_name_and_date_filters() -> None:
    number = format_customer_number(1023)
    store: CustomerStore = FakeStore(
        [_candidate(1, "Ally", "Macbeal", ALLY_DOB, customer_number=number)]
    )

    matches = asyncio.run(
        find_customers(
            store,
            customer_number=number,
            first_name="Someone",
            last_name="Else",
            date_of_birth=PartialDate(1970, 1, 1),
        )
    )

    assert len(matches) == 1


# --- FORM-218: parse_partial_date ---------------------------------------------------------------


def test_story_218_parse_partial_date_year_only() -> None:
    assert parse_partial_date("1994") == PartialDate(1994, None, None)


def test_story_218_parse_partial_date_year_month() -> None:
    assert parse_partial_date("1994-11") == PartialDate(1994, 11, None)


def test_story_218_parse_partial_date_full_date() -> None:
    assert parse_partial_date("1994-11-20") == PartialDate(1994, 11, 20)


def test_story_218_parse_partial_date_invalid_shapes_are_none() -> None:
    assert parse_partial_date("not-a-date") is None
    assert parse_partial_date("1994-13") is None  # bad month
    assert parse_partial_date("1994-02-30") is None  # bad day
    assert parse_partial_date("94-11-20") is None  # not 4-digit year
    assert parse_partial_date("") is None
