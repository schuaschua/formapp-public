"""Story FORM-218: the customer-number check digit (CAP-10, spine AD-13)."""

import pytest

from domain.customer_numbers import format_customer_number, is_valid, normalize, sequence_of


def test_story_218_format_produces_the_cus_prefixed_shape() -> None:
    number = format_customer_number(1002)

    assert number.startswith("CUS-")
    assert len(number) == len("CUS-") + 5  # 4-digit sequence + 1 check digit


def test_story_218_a_formatted_number_is_valid_and_round_trips_its_sequence() -> None:
    number = format_customer_number(1002)

    assert is_valid(number)
    assert sequence_of(number) == 1002


def test_story_218_altering_the_last_digit_invalidates_it() -> None:
    number = format_customer_number(1002)
    altered = number[:-1] + str((int(number[-1]) + 1) % 10)

    assert altered != number
    assert not is_valid(altered)
    assert sequence_of(altered) is None


def test_story_218_altering_any_body_digit_invalidates_it() -> None:
    # Every single-digit change to the 4-digit body must fail the check digit for at least the
    # digits actually exercised here (Luhn catches every single-digit substitution).
    number = format_customer_number(1002)
    prefix, body, check = number[:4], number[4:8], number[8:]
    for index in range(len(body)):
        for replacement in "0123456789":
            if replacement == body[index]:
                continue
            altered_body = body[:index] + replacement + body[index + 1 :]
            altered = f"{prefix}{altered_body}{check}"
            assert sequence_of(altered) is None, f"{altered} unexpectedly validated"


def test_story_218_wrong_prefix_is_invalid() -> None:
    number = format_customer_number(1002)
    assert not is_valid("XYZ" + number[3:])


def test_story_218_wrong_length_is_invalid() -> None:
    assert not is_valid("CUS-100")
    assert not is_valid("CUS-100025")


def test_story_218_non_numeric_body_is_invalid() -> None:
    assert not is_valid("CUS-ABCDE")


def test_story_218_case_and_whitespace_insensitive() -> None:
    number = format_customer_number(1002)

    assert is_valid(number.lower())
    assert is_valid(f"  {number}  ")
    assert normalize(number.lower()) == number
    assert normalize(f" {number.lower()} ") == number


def test_story_218_non_string_is_invalid() -> None:
    assert sequence_of(123) is None  # type: ignore[arg-type]


def test_story_218_out_of_range_sequence_raises() -> None:
    with pytest.raises(ValueError):
        format_customer_number(-1)
    with pytest.raises(ValueError):
        format_customer_number(10_000)


def test_story_218_normalize_of_an_invalid_number_is_none() -> None:
    assert normalize("not-a-number") is None
    assert normalize("CUS-99999") is None  # a check digit that doesn't fit any real number


def test_story_218_sequence_zero_is_a_valid_edge_case() -> None:
    number = format_customer_number(0)

    assert number.startswith("CUS-0000")
    assert sequence_of(number) == 0
