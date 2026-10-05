"""Story 2.2 Part A: age bands, the price rule and the quote, against the seed catalogue."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from domain.pricing import (
    PRICING_TIMEZONE,
    ItemPrice,
    Quote,
    QuoteLine,
    age_at,
    band_index,
    build_quote,
    item_price,
)


@dataclass(frozen=True)
class Rider:
    code: str
    name: str
    baseline_monthly: Decimal


@dataclass(frozen=True)
class Product:
    name: str
    baseline_monthly: Decimal
    riders: tuple[Rider, ...] = ()


# Seed content (form-content-draft.md, Products and Riders): synthetic.
FSH = Product(
    "FamilyShield Life & Health",
    Decimal(160),
    (
        Rider("R04", "Hospital cash", Decimal(15)),
        Rider("R05", "Critical illness", Decimal(25)),
        Rider("R06", "Child cover", Decimal(12)),
        Rider("R07", "Maternity & newborn", Decimal(30)),
    ),
)
LT20 = Product(
    "SecureLife Term",
    Decimal(60),
    (
        Rider("R01", "Critical illness", Decimal(20)),
        Rider("R02", "Accidental death", Decimal(8)),
        Rider("R03", "Waiver of premium", Decimal(5)),
    ),
)
LWL = Product(
    "Legacy Whole Life",
    Decimal(260),
    (
        Rider("R12", "Waiver of premium", Decimal(10)),
        Rider("R13", "Accidental death", Decimal(12)),
    ),
)

ALLY_DOB = date(1994, 11, 20)
CREATED = datetime(2026, 9, 25, 3, 0, tzinfo=UTC)


def _created_at_age(age: int) -> tuple[date, datetime]:
    """A date of birth that makes the insured exactly `age` at CREATED."""
    return date(CREATED.year - age, 1, 1), CREATED


def test_story_2_2_ally_quote() -> None:
    quote = build_quote(FSH, ["R07"], ALLY_DOB, CREATED)

    assert quote == Quote(
        monthly=Decimal("219.95"),
        yearly=Decimal("2507.42"),
        lines=(
            QuoteLine(
                "FamilyShield Life & Health", Decimal("185.22"), Decimal("2111.51")
            ),
            QuoteLine("Maternity & newborn", Decimal("34.73"), Decimal("395.91")),
        ),
    )


def test_story_2_2_ally_is_31_in_band_3() -> None:
    assert age_at(ALLY_DOB, CREATED) == 31
    assert band_index(31) == 3


def test_story_2_2_youngest_lt20_at_18() -> None:
    dob, created = _created_at_age(18)

    quote = build_quote(LT20, [], dob, created)

    assert quote is not None
    assert (quote.monthly, quote.yearly) == (Decimal("60.00"), Decimal("684.00"))


def test_story_2_2_oldest_lwl_at_70() -> None:
    dob, created = _created_at_age(70)

    quote = build_quote(LWL, [], dob, created)

    assert quote is not None
    assert (quote.monthly, quote.yearly) == (Decimal("423.51"), Decimal("4828.04"))


@pytest.mark.parametrize(
    ("low", "high", "index"),
    [
        (0, 18, 0),
        (19, 25, 1),
        (26, 30, 2),
        (31, 35, 3),
        (36, 40, 4),
        (41, 45, 5),
        (46, 50, 6),
        (51, 55, 7),
        (56, 60, 8),
        (61, 65, 9),
        (66, 70, 10),
    ],
)
def test_story_2_2_every_band_lower_and_upper_age(
    low: int, high: int, index: int
) -> None:
    assert band_index(low) == index
    assert band_index(high) == index


@pytest.mark.parametrize(
    ("below", "above", "indexes"),
    [(18, 19, (0, 1)), (25, 26, (1, 2)), (65, 66, (9, 10))],
)
def test_story_2_2_band_edges(below: int, above: int, indexes: tuple[int, int]) -> None:
    assert (band_index(below), band_index(above)) == indexes


@pytest.mark.parametrize("age", [71, 90, -1])
def test_story_2_2_age_outside_0_to_70_has_no_band(age: int) -> None:
    assert band_index(age) is None


def test_story_2_2_over_70_gives_no_price() -> None:
    dob, created = _created_at_age(71)

    assert build_quote(LWL, [], dob, created) is None


def test_story_2_2_dob_after_created_at_gives_no_price() -> None:
    assert build_quote(LT20, [], date(2026, 12, 1), CREATED) is None


def test_story_2_2_age_turns_on_the_birthday() -> None:
    created = datetime(2026, 5, 10, 4, 0, tzinfo=UTC)

    assert age_at(date(2008, 5, 10), created) == 18
    assert age_at(date(2008, 5, 11), created) == 17


def test_story_2_2_age_uses_the_malaysian_date_of_created_at() -> None:
    birthday = date(2008, 9, 26)

    # 00:00 and 07:59 MYT on the 26th are still the 25th in UTC.
    assert age_at(birthday, datetime(2026, 9, 25, 16, 0, tzinfo=UTC)) == 18
    assert age_at(birthday, datetime(2026, 9, 25, 23, 59, tzinfo=UTC)) == 18
    # 23:59 MYT on the 25th.
    assert age_at(birthday, datetime(2026, 9, 25, 15, 59, tzinfo=UTC)) == 17


def test_story_2_2_age_ignores_the_offset_created_at_is_given_in() -> None:
    other_zone = timezone(timedelta(hours=-5))
    instant = datetime(2026, 9, 25, 16, 0, tzinfo=UTC)

    assert age_at(date(2008, 9, 26), instant.astimezone(other_zone)) == 18


def test_story_2_2_leap_day_birthday_counts_from_1_march() -> None:
    dob = date(2008, 2, 29)

    assert age_at(dob, datetime(2026, 2, 28, 4, 0, tzinfo=UTC)) == 17
    assert age_at(dob, datetime(2026, 3, 1, 4, 0, tzinfo=UTC)) == 18
    assert age_at(dob, datetime(2028, 2, 29, 4, 0, tzinfo=UTC)) == 20


def test_story_2_2_pricing_timezone_is_kuala_lumpur_utc_plus_8() -> None:
    assert PRICING_TIMEZONE.utcoffset(None) == timedelta(hours=8)
    assert PRICING_TIMEZONE.tzname(None) == "Asia/Kuala_Lumpur"


def test_story_2_2_naive_created_at_is_a_programming_error() -> None:
    # The naive value is the point of this test.
    naive = datetime(2026, 9, 25, 3, 0)  # noqa: DTZ001

    with pytest.raises(ValueError):
        age_at(ALLY_DOB, naive)
    with pytest.raises(ValueError):
        build_quote(FSH, [], ALLY_DOB, naive)
    with pytest.raises(ValueError):
        build_quote(None, [], None, naive)


def test_story_2_2_no_product_or_no_dob_gives_no_quote() -> None:
    assert build_quote(None, [], ALLY_DOB, CREATED) is None
    assert build_quote(FSH, ["R07"], None, CREATED) is None


def test_story_2_2_foreign_rider_gives_no_quote() -> None:
    # LT20's critical illness is not one of FSH's riders.
    assert build_quote(FSH, ["R07", "R01"], ALLY_DOB, CREATED) is None


def test_story_2_2_product_only_has_one_line_equal_to_the_totals() -> None:
    quote = build_quote(FSH, [], ALLY_DOB, CREATED)

    assert quote is not None
    assert quote.lines == (
        QuoteLine("FamilyShield Life & Health", quote.monthly, quote.yearly),
    )
    assert (quote.monthly, quote.yearly) == (Decimal("185.22"), Decimal("2111.51"))


def test_story_2_2_riders_follow_the_product_in_the_order_chosen() -> None:
    quote = build_quote(FSH, ["R07", "R04", "R05"], ALLY_DOB, CREATED)

    assert quote is not None
    assert [line.item for line in quote.lines] == [
        "FamilyShield Life & Health",
        "Maternity & newborn",
        "Hospital cash",
        "Critical illness",
    ]


def test_story_2_2_each_rider_priced_on_its_own_baseline() -> None:
    quote = build_quote(FSH, ["R07"], ALLY_DOB, CREATED)

    assert quote is not None
    rider = item_price(Decimal(30), 3)
    assert quote.lines[1] == QuoteLine(
        "Maternity & newborn", rider.monthly, rider.yearly
    )


def test_story_2_2_totals_rounded_from_unrounded_sums_not_from_lines() -> None:
    # A product and two riders of 0.005 each: every line rounds up to 0.01, but the sum 0.015 rounds to 0.02.
    tiny = Product(
        "Tiny",
        Decimal("0.005"),
        (
            Rider("A", "A", Decimal("0.005")),
            Rider("B", "B", Decimal("0.005")),
        ),
    )
    dob, created = _created_at_age(18)

    quote = build_quote(tiny, ["A", "B"], dob, created)

    assert quote is not None
    assert [line.monthly for line in quote.lines] == [Decimal("0.01")] * 3
    assert sum(line.monthly for line in quote.lines) == Decimal("0.03")
    assert quote.monthly == Decimal("0.02")
    assert [line.yearly for line in quote.lines] == [Decimal("0.06")] * 3
    assert quote.yearly == Decimal("0.17")


def test_story_2_2_lwl_priced_at_70_and_not_on_the_71st_birthday() -> None:
    dob = date(1955, 9, 26)

    # 00:30 MYT on 25 and 26 September 2026.
    at_70 = build_quote(LWL, [], dob, datetime(2026, 9, 24, 16, 30, tzinfo=UTC))
    at_71 = build_quote(LWL, [], dob, datetime(2026, 9, 25, 16, 30, tzinfo=UTC))

    assert at_70 is not None
    assert (at_70.monthly, at_70.yearly) == (Decimal("423.51"), Decimal("4828.04"))
    assert at_71 is None


def test_story_2_2_item_price_uses_exact_multiplier_and_rounds_once() -> None:
    # The 4-decimal table multiplier 1.1576 would give 2111.46 yearly.
    assert item_price(Decimal(160), 3) == ItemPrice(
        Decimal("185.22"), Decimal("2111.51")
    )
    # Yearly from the unrounded monthly (34.72875), not from 34.73 (which gives 395.92).
    assert item_price(Decimal(30), 3).yearly == Decimal("395.91")


def test_story_2_2_rounding_is_half_up() -> None:
    # 0.125 x 1.05^0 = 0.125: half up gives 0.13 where banker's rounding gives 0.12.
    assert item_price(Decimal("0.125"), 0).monthly == Decimal("0.13")
