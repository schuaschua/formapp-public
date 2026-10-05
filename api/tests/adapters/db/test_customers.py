"""Story 5.1/FORM-218: `SqlCustomerStore` filters `customer` by an exact customer number, or by
whichever date-of-birth parts are given (AD-3, AD-13), against migration 0013's seeded rows. Name
matching (exact and fuzzy) is `domain.customers.find_customers`'s own job -- these tests go
through it, same as the real caller, rather than poking `candidates()` directly."""

import asyncio
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from adapters.db.customers import SqlCustomerStore
from adapters.db.engine import build_password_source, create_engine
from adapters.settings import Settings
from domain.customer_numbers import format_customer_number
from domain.customers import PartialDate, find_customers
from tests.fakes import FakeClock

Admin = Callable[[str], psycopg.Connection[Any]]

ALLY_CUSTOMER_NUMBER = format_customer_number(1000)  # migration 0015's first backfilled number


@pytest.fixture
def engine(db_settings: Settings, migrated_db: str) -> Iterator[AsyncEngine]:
    settings = db_settings.model_copy(update={"database_name": migrated_db})
    built = create_engine(settings, build_password_source(settings, FakeClock()))
    try:
        yield built
    finally:
        asyncio.run(built.dispose())


def test_story_5_1_finds_the_demo_customer_case_insensitively(
    engine: AsyncEngine,
) -> None:
    store = SqlCustomerStore(engine)

    matches = asyncio.run(
        find_customers(
            store,
            first_name="ally",
            last_name="MACBEAL",
            date_of_birth=PartialDate(1994, 11, 20),
        )
    )

    assert len(matches) == 1
    match = matches[0]
    assert (match.first_name, match.last_name) == ("Ally", "Macbeal")
    assert match.city == "Petaling Jaya"
    assert match.date_of_birth.isoformat() == "1994-11-20"
    assert match.customer_number  # migration 0015 backfilled one


def test_story_5_1_wrong_date_of_birth_finds_nothing(engine: AsyncEngine) -> None:
    store = SqlCustomerStore(engine)

    matches = asyncio.run(
        find_customers(
            store,
            first_name="Ally",
            last_name="Macbeal",
            date_of_birth=PartialDate(1994, 11, 21),
        )
    )

    assert matches == ()


def test_story_5_1_unknown_name_finds_nothing(engine: AsyncEngine) -> None:
    store = SqlCustomerStore(engine)

    matches = asyncio.run(
        find_customers(
            store,
            first_name="Nobody",
            last_name="Synthetic",
            date_of_birth=PartialDate(1994, 11, 20),
        )
    )

    assert matches == ()


def test_story_5_1_similar_name_rows_are_told_apart_by_date_of_birth(
    engine: AsyncEngine,
) -> None:
    store = SqlCustomerStore(engine)

    wei_ming = asyncio.run(
        find_customers(
            store,
            first_name="Tan",
            last_name="Wei Ming",
            date_of_birth=PartialDate(1988, 3, 14),
        )
    )
    wei_min = asyncio.run(
        find_customers(
            store,
            first_name="Tan",
            last_name="Wei Min",
            date_of_birth=PartialDate(1990, 7, 22),
        )
    )

    assert [match.city for match in wei_ming] == ["George Town"]
    assert [match.city for match in wei_min] == ["Kota Kinabalu"]


def test_story_218_first_name_and_year_month_find_the_unique_seeded_customer(
    engine: AsyncEngine,
) -> None:
    store = SqlCustomerStore(engine)

    matches = asyncio.run(
        find_customers(store, first_name="ally", date_of_birth=PartialDate(1994, 11, None))
    )

    assert len(matches) == 1
    assert matches[0].last_name == "Macbeal"


def test_story_218_first_name_and_year_alone_is_ambiguous_for_the_seeded_tans(
    engine: AsyncEngine,
) -> None:
    store = SqlCustomerStore(engine)

    matches = asyncio.run(
        find_customers(store, first_name="Tan", date_of_birth=PartialDate(1988, None, None))
    )

    # Only "Wei Ming" (1988) matches the year alone; "Wei Min" is 1990.
    assert [match.last_name for match in matches] == ["Wei Ming"]


def test_story_218_close_spelling_of_the_seeded_last_name_matches(
    engine: AsyncEngine,
) -> None:
    store = SqlCustomerStore(engine)

    matches = asyncio.run(find_customers(store, first_name="Ally", last_name="mcbeal"))

    assert len(matches) == 1
    assert matches[0].last_name == "Macbeal"


def test_story_218_exact_customer_number_finds_the_seeded_customer(
    engine: AsyncEngine,
) -> None:
    store = SqlCustomerStore(engine)

    matches = asyncio.run(find_customers(store, customer_number=ALLY_CUSTOMER_NUMBER))

    assert len(matches) == 1
    assert matches[0].last_name == "Macbeal"


def test_story_218_altered_customer_number_check_digit_finds_nothing(
    engine: AsyncEngine,
) -> None:
    store = SqlCustomerStore(engine)
    altered = (
        ALLY_CUSTOMER_NUMBER[:-1]
        + str((int(ALLY_CUSTOMER_NUMBER[-1]) + 1) % 10)
    )

    matches = asyncio.run(find_customers(store, customer_number=altered))

    assert matches == ()


def test_story_218_no_filters_at_all_never_touches_the_database(
    engine: AsyncEngine,
) -> None:
    store = SqlCustomerStore(engine)

    matches = asyncio.run(find_customers(store))

    assert matches == ()


def test_story_218_first_name_only_search_finds_a_customer_beyond_the_candidate_band(
    engine: AsyncEngine, admin: Admin, migrated_db: str
) -> None:
    """Review fix: with no date parts given, the store's SQL must narrow by the given name too
    (not only filter by date and let Python match names over an id-ordered first-50 scan) -- 60
    filler rows, every one sorting before the target by id, prove a first-name-only search still
    finds it on a table bigger than `_CANDIDATE_BAND`."""
    with admin(migrated_db) as connection:
        for index in range(60):
            connection.execute(
                "INSERT INTO customer (id, first_name, last_name, date_of_birth, sex_at_birth, "
                "country_of_origin, country_of_residence, id_number, email, mobile, "
                "street_address, occupation, marital_status, income_range, city, postcode, "
                "customer_number) VALUES (%s, %s, 'Filler', '1980-01-01', 'female', 'MY', 'MY', "
                "%s, %s, '0100000000', '1 Filler Rd', 'clerk', 'single', 'RM3,000-RM4,999', "
                "'Kuala Lumpur', '50000', %s)",
                (
                    UUID(f"00000000-0000-3000-0000-{index:012d}"),
                    f"Filler{index}",
                    f"S{index:07d}",
                    f"filler{index}@example.test",
                    format_customer_number(2000 + index),
                ),
            )
        connection.execute(
            "INSERT INTO customer (id, first_name, last_name, date_of_birth, sex_at_birth, "
            "country_of_origin, country_of_residence, id_number, email, mobile, "
            "street_address, occupation, marital_status, income_range, city, postcode, "
            "customer_number) VALUES (%s, 'Zorawar', 'Synthetic', '1975-05-05', 'male', 'MY', "
            "'MY', 'S9999999', 'zorawar@example.test', '0199999999', '2 Target Rd', 'engineer', "
            "'married', 'RM5,000-RM9,999', 'Johor Bahru', '80000', %s)",
            (
                UUID("00000000-0000-3000-0001-000000000000"),
                format_customer_number(2999),
            ),
        )

    store = SqlCustomerStore(engine)

    matches = asyncio.run(find_customers(store, first_name="Zorawar"))

    assert [match.last_name for match in matches] == ["Synthetic"]
